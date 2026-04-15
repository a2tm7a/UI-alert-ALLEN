"""
WatchDog — AuthSession
=======================
Manages login and stream-profile switching for WatchDog's authenticated
scraping mode (Phase 2 / R-20, R-21).

Credentials are read from environment variables (preferred) or from
test_credentials.json as a local-dev fallback:
    WATCHDOG_TEST_FORM_ID      — test account phone / email / form_id
    WATCHDOG_TEST_PASSWORD     — test account password

Stream profiles supported: JEE, NEET, Classes610

Usage::

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(**desktop_kwargs)
        stealth.apply_stealth_sync(context)

        session = AuthSession(context)
        session.login()
        session.switch_profile("JEE")
        # ... hand context to ScraperEngine for scraping ...
        session.switch_profile("NEET")
        # ...
        session.close()
"""

import json
import logging
import os
import re
import time
from typing import Any, Optional

from playwright.sync_api import BrowserContext, Locator, Page

# ---------------------------------------------------------------------------
# Selectors — confirmed via scripts/discover_auth_selectors.py on 2026-04-15
# ---------------------------------------------------------------------------

# allen.in uses a modal login triggered from the homepage nav bar.
# The modal offers three flows; we use the Form ID flow.
BASE_URL = "https://allen.in"

# Step 1: Nav "Login" button that opens the modal
NAV_LOGIN_BUTTON = "button[data-testid='loginCtaButton']"

# Headless allen.in can be slow; 8s was too tight for modal paint + hydration.
_AUTH_MODAL_OPEN_MS = int(os.environ.get("WATCHDOG_AUTH_MODAL_MS", "25000"))

# Poll for a *visible* "Continue with Form ID" (duplicate DOM nodes are often hidden).
_FORM_ID_FLOW_MS = int(os.environ.get("WATCHDOG_FORM_ID_FLOW_MS", "10000"))
_FORM_ID_FLOW_POLL_S = 0.1

# Poll for visible credential fields after the Form ID method transition.
_CRED_FIELD_MS = int(os.environ.get("WATCHDOG_CRED_FIELD_MS", "18000"))
_CRED_FIELD_POLL_S = 0.12

# Step 4–6: credential fields — use login_credentials_panel_locator() after Form ID click.
FORM_ID_FIELD_SELECTORS: tuple[str, ...] = (
    "input[name='formId']",
    "input#formId",
    "input[placeholder*='Form ID']",
    "input[placeholder*='form id']",
    "input[placeholder*='Form Id']",
)
PASSWORD_INNER = "input[type='password']"
SUBMIT_BUTTON_SELECTORS: tuple[str, ...] = (
    "button[type='submit']",
    "button:has-text('Login')",
    "button:has-text('Sign In')",
)

# Dialog must contain at least one of these to count as the credentials panel.
_CREDENTIAL_FIELD_HAS = ", ".join(FORM_ID_FIELD_SELECTORS + (PASSWORD_INNER,))

# Optional UI signals that logged-in chrome is present (see AUTH_UI_FLOW.md).
LOGGED_IN_POSITIVE_SELECTORS: tuple[str, ...] = (
    "text=Log out",
    "text=Logout",
    "[data-testid*='profile']",
    "[data-testid*='Profile']",
)

# Confirms a successful login — nav "Login" button disappears and a user
# avatar / profile icon appears. We detect login by absence of the nav button.
NAV_LOGIN_STILL_VISIBLE = "button[data-testid='loginCtaButton']"

# Indicators in URL or page text that signal session expiry / logged-out state
SESSION_EXPIRY_INDICATORS = [
    "session expired",
    "please log in",
    "please sign in",
]

# Profile → Change stream/class/board (see AUTH_UI_FLOW.md § Profile change).
PROFILE_PAGE_URL = "https://allen.in/profile"
# Exact pill labels in the *Change your preference* modal (stream row).
# These match the visible text of the short pill chips in the UI.
PROFILE_STREAM_LABELS: dict[str, str] = {
    "JEE": "JEE",
    "NEET": "NEET",
    "Classes610": "Class 6-10",
}
# Entry control for the profile editor (tune via discover on /profile).
PROFILE_CHANGE_BUTTON = (
    "button:has-text('Change'), a:has-text('Change'), [role='button']:has-text('Change')"
)

# Verbose ``[AUTH][profile]`` logs + ``reports/profile-debug-*.txt`` + ``.png`` on failures.
PROFILE_DEBUG_ENV = "WATCHDOG_PROFILE_DEBUG"

# Promo / survey layers appear after first paint; wait before opening Login.
POST_LOAD_LATE_POPUP_SEC = 12.0


def _form_id_flow_budget_ms() -> int:
    return int(os.environ.get("WATCHDOG_FORM_ID_FLOW_MS", str(_FORM_ID_FLOW_MS)))


def _cred_field_budget_ms() -> int:
    return int(os.environ.get("WATCHDOG_CRED_FIELD_MS", str(_CRED_FIELD_MS)))


def _goto_spa_no_networkidle(page: Page, url: str) -> None:
    """
    Open *url* without wait_until=networkidle.

    Marketing SPAs (allen.in) keep sockets / beacons open; networkidle can hang
    until Playwright hits the navigation timeout even when the UI is usable.
    """
    timeout_ms = int(os.environ.get("WATCHDOG_GOTO_TIMEOUT_MS", "60000"))
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        page.wait_for_load_state("load", timeout=min(25_000, timeout_ms))
    except Exception:
        pass
    time.sleep(0.4)


def _visible_dialog_or_body(page: Page, timeout_ms: int) -> Locator:
    """First visible [role=dialog], else full page (last resort for scoped locators)."""
    any_dlg = page.locator('[role="dialog"]')
    if any_dlg.count() > 0:
        try:
            any_dlg.first.wait_for(state="visible", timeout=timeout_ms)
            return any_dlg.first
        except Exception:
            pass
    return page.locator("body")


def _dismiss_optional_overlays(page: Page) -> None:
    """Close cookie / CMP banners that sit above the login modal (best-effort)."""
    candidates = (
        "button:has-text('Accept')",
        "button:has-text('Accept all')",
        "button:has-text('I understand')",
        "button:has-text('Agree')",
        "button:has-text('Not now')",
        "button:has-text('Maybe later')",
        "[aria-label='Close']",
        "button[aria-label='Close']",
    )
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=600):
                loc.click(timeout=2_000)
                time.sleep(0.25)
        except Exception:
            continue

    # allen.in promo: full-viewport DIV[data-testid="dialog"] (bg-overlay) can sit above
    # the nav Login CTA.
    try:
        page.keyboard.press("Escape")
        time.sleep(0.2)
        page.keyboard.press("Escape")
        time.sleep(0.2)
    except Exception:
        pass

    dialog_close_selectors = (
        '[data-testid="dialog"] button[aria-label="Close"]',
        '[data-testid="dialog"] [aria-label="Close"]',
        '[data-testid="dialog"] button:has-text("Close")',
        '[data-testid="dialog"] button:has-text("Skip")',
        '[data-testid="dialog"] button:has-text("Not now")',
        '[data-testid="dialog"] button',
    )
    try:
        dlg = page.locator('[data-testid="dialog"]')
        if dlg.count() > 0 and dlg.first.is_visible(timeout=800):
            for sel in dialog_close_selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=500):
                        loc.click(timeout=2_000)
                        time.sleep(0.35)
                        break
                except Exception:
                    continue
    except Exception:
        pass


def login_drawer_locator(page: Page) -> Locator:
    """
    The login UI is a drawer/modal: a [role="dialog"] that contains the method
    picker (Form ID vs OTP vs username). Scoping step 3 here avoids clicking
    hidden duplicate buttons outside the open drawer.
    """
    method_picker = (
        "button[data-testid='FormIdLoginButtonWeb'], "
        "button[data-testid*='FormIdLogin'], "
        "button[data-testid='submitOTPButton'], "
        "button[data-testid='usernameLoginButtonWeb']"
    )
    drawer = page.locator('[role="dialog"]').filter(has=page.locator(method_picker))
    if drawer.count() > 0:
        try:
            drawer.first.wait_for(state="visible", timeout=_AUTH_MODAL_OPEN_MS)
            return drawer.first
        except Exception:
            pass
    return _visible_dialog_or_body(page, min(12_000, _AUTH_MODAL_OPEN_MS))


def click_visible_form_id_flow_button(scope: Locator) -> None:
    """
    Click the first *visible* and *enabled* Continue-with-Form-ID control inside
    *scope*. allen.in keeps duplicate ``FormIdLoginButtonWeb`` nodes (e.g. mobile
    vs desktop); ``.first`` often resolves to a hidden one, so a single long
    ``wait_for(visible)`` can time out. We poll with ``WATCHDOG_FORM_ID_FLOW_MS``
    (default 10s) and short slices instead.
    """
    budget_ms = _form_id_flow_budget_ms()
    deadline = time.time() + budget_ms / 1000.0
    primary = scope.locator('button[data-testid="FormIdLoginButtonWeb"]')
    by_label = scope.get_by_role(
        "button",
        name=re.compile(r"continue\s+with\s+form\s*id", re.I),
    )

    while time.time() < deadline:
        for loc in (primary, by_label):
            try:
                n = loc.count()
            except Exception:
                n = 0
            for i in range(min(n, 10)):
                cell = loc.nth(i)
                try:
                    if not cell.is_visible():
                        continue
                    try:
                        if not cell.is_enabled():
                            continue
                    except Exception:
                        pass
                    cell.click(timeout=5_000)
                    return
                except Exception:
                    continue
        time.sleep(_FORM_ID_FLOW_POLL_S)

    raise RuntimeError(
        f"[AUTH] No visible, enabled Continue-with-Form-ID control within {budget_ms}ms "
        "(duplicate hidden nodes are common — increase WATCHDOG_FORM_ID_FLOW_MS if needed)."
    )


def _auth_ui_snapshot(page: Page) -> dict[str, Any]:
    """Compact DOM counts for tracing which login step the UI is on."""
    try:
        return page.evaluate(
            """() => {
              const ids = ['loginCtaButton','FormIdLoginButtonWeb','submitOTPButton',
                'usernameLoginButtonWeb'];
              const testIds = {};
              for (const id of ids) {
                testIds[id] = document.querySelectorAll('[data-testid="' + id + '"]').length;
              }
              return {
                testIds,
                dialogRoleCount: document.querySelectorAll('[role="dialog"]').length,
                dataTestIdDialog: document.querySelectorAll('[data-testid="dialog"]').length,
              };
            }"""
        )
    except Exception as exc:
        return {"error": str(exc)}


def login_credentials_panel_locator(page: Page) -> Locator:
    """
    After "Continue with Form ID", the method-picker button may unmount. Resolve the
    dialog that **contains credential inputs** so we do not fall back to ``body``
    and fill the wrong field (e.g. homepage FullName).
    """
    dlg = page.locator('[role="dialog"]').filter(has=page.locator(_CREDENTIAL_FIELD_HAS))
    if dlg.count() > 0:
        try:
            dlg.first.wait_for(state="visible", timeout=min(15_000, _AUTH_MODAL_OPEN_MS))
            return dlg.first
        except Exception:
            pass
    return _visible_dialog_or_body(page, 5_000)


def fill_first_visible_in_scope(
    scope: Locator,
    selectors: tuple[str, ...],
    value: str,
    *,
    what: str = "field",
) -> None:
    """Fill the first matching *visible* control (skip hidden duplicates)."""
    budget_ms = _cred_field_budget_ms()
    deadline = time.time() + budget_ms / 1000.0
    while time.time() < deadline:
        for sel in selectors:
            loc = scope.locator(sel)
            try:
                n = loc.count()
            except Exception:
                n = 0
            for i in range(min(n, 10)):
                cell = loc.nth(i)
                try:
                    if not cell.is_visible():
                        continue
                    try:
                        if not cell.is_enabled():
                            continue
                    except Exception:
                        pass
                    cell.fill(value, timeout=5_000)
                    return
                except Exception:
                    continue
        time.sleep(_CRED_FIELD_POLL_S)
    raise RuntimeError(
        f"[AUTH] No visible, enabled {what} matched within {budget_ms}ms: {selectors!r}"
    )


def click_first_visible_submit_in_scope(scope: Locator) -> None:
    budget_ms = _cred_field_budget_ms()
    deadline = time.time() + budget_ms / 1000.0
    while time.time() < deadline:
        for sel in SUBMIT_BUTTON_SELECTORS:
            loc = scope.locator(sel)
            try:
                n = loc.count()
            except Exception:
                n = 0
            for i in range(min(n, 8)):
                cell = loc.nth(i)
                try:
                    if not cell.is_visible() or not cell.is_enabled():
                        continue
                    cell.click(timeout=5_000)
                    return
                except Exception:
                    continue
        time.sleep(_CRED_FIELD_POLL_S)
    raise RuntimeError(
        f"[AUTH] No visible, enabled submit control within {budget_ms}ms: {SUBMIT_BUTTON_SELECTORS!r}"
    )


def _profile_change_dialog_budget_ms() -> int:
    return int(os.environ.get("WATCHDOG_PROFILE_DIALOG_MS", "25000"))


_PREF_MODAL_TITLE = "Change your preference"


def _pref_modal_title_visible(page: Page, timeout_ms: int = 2_000) -> bool:
    """True when the 'Change your preference' heading is rendered on screen."""
    try:
        return page.get_by_text(_PREF_MODAL_TITLE, exact=False).first.is_visible(
            timeout=timeout_ms
        )
    except Exception:
        return False


def _active_profile_dialog(page: Page) -> Locator:
    """
    Return a Locator that scopes to the *Change your preference* modal.

    allen.in renders the modal as a portal wrapper ``div[role="dialog"]`` that
    Playwright does **not** consider "visible" (zero-size transparent container),
    even though its children — the pill rows — are clearly on screen.

    Strategy (three tiers, polled):

    1. ``[role="dialog"]`` / ``[role="alertdialog"]`` with a Playwright-visible
       wrapper — ideal; works when the wrapper has dimensions.
    2. ``[role="dialog"]`` wrapper whose **content** ("Change your preference"
       title) is visible — the allen.in portal case.
    3. ``body`` fallback — title is visible on page but no dialog role found.
    """
    budget_ms = _profile_change_dialog_budget_ms()
    deadline = time.time() + budget_ms / 1000.0
    last_err: Optional[Exception] = None

    while time.time() < deadline:
        # ── Tier 1: role-based + wrapper itself visible ──────────────────────
        for sel in ('[role="dialog"]', '[role="alertdialog"]'):
            try:
                d = page.locator(sel)
                if d.count() == 0:
                    continue
                tail = d.last
                tail.wait_for(state="visible", timeout=2_000)
                logging.debug("[AUTH][profile] dialog found via %r (visible wrapper)", sel)
                return tail
            except Exception as exc:
                last_err = exc
                continue

        # ── Tier 2: portal wrapper not visible but content is ────────────────
        # allen.in uses a transparent <div role="dialog"> as a React-portal
        # mount point; its CSS makes Playwright consider it hidden.  Accept it
        # when the modal TITLE is visible anywhere inside the wrapper.
        for sel in ('[role="dialog"]', '[role="alertdialog"]'):
            try:
                d = page.locator(sel)
                if d.count() == 0:
                    continue
                tail = d.last
                title_in_dialog = tail.get_by_text(_PREF_MODAL_TITLE, exact=False)
                if (
                    title_in_dialog.count() > 0
                    and title_in_dialog.first.is_visible(timeout=1_000)
                ):
                    logging.debug(
                        "[AUTH][profile] dialog found via %r (portal: title visible inside)",
                        sel,
                    )
                    return tail
            except Exception as exc:
                last_err = exc
                continue

        # ── Tier 3: title visible on page, no dialog role ────────────────────
        try:
            if _pref_modal_title_visible(page, timeout_ms=1_000):
                logging.debug(
                    "[AUTH][profile] dialog not found by role — using body as scope "
                    "(title '%s' is visible on page)",
                    _PREF_MODAL_TITLE,
                )
                return page.locator("body")
        except Exception as exc:
            last_err = exc

        time.sleep(0.2)

    raise RuntimeError(
        f"[AUTH] No visible profile Change layer within {budget_ms}ms: {last_err!r}"
    )


def _open_profile_change_modal(page: Page) -> None:
    """
    Click the profile **Change** control. Prefer ``main`` so we do not hit a
    duplicate Change elsewhere on the page.
    """
    groups = (
        page.locator("main").get_by_role("button", name=re.compile(r"^\s*Change\s*$", re.I)),
        page.locator("main").locator("a").filter(has_text=re.compile(r"^\s*Change\s*$", re.I)),
        page.locator(PROFILE_CHANGE_BUTTON),
    )
    for g in groups:
        try:
            n = g.count()
        except Exception:
            n = 0
        for i in range(min(n, 16)):
            cell = g.nth(i)
            try:
                if not cell.is_visible(timeout=1_200):
                    continue
                cell.scroll_into_view_if_needed(timeout=5_000)
                cell.click(timeout=12_000)
                time.sleep(0.6)
                return
            except Exception:
                continue
    raise RuntimeError("[AUTH] No visible Change control on profile page.")


def _profile_debug_verbose() -> bool:
    return os.environ.get(PROFILE_DEBUG_ENV, "").lower() in ("1", "true", "yes")


def _excerpt_one_line(s: str, max_len: int = 1200) -> str:
    t = " ".join((s or "").split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 3] + "..."


def _locator_page(loc: Locator) -> Optional[Page]:
    try:
        p = getattr(loc, "page", None)
        return p if p is not None else None
    except Exception:
        return None


def _profile_dialog_count_summary(page: Page) -> str:
    parts: list[str] = []
    try:
        n = page.locator('[role="dialog"]').count()
        parts.append(f"dialog_count={n}")
    except Exception as exc:
        parts.append(f"dialog_count_err={exc!r}")
    try:
        na = page.locator('[role="alertdialog"]').count()
        parts.append(f"alertdialog_count={na}")
    except Exception:
        pass
    return " ".join(parts)


def _log_profile_change_context(
    page: Page,
    popup: Optional[Locator],
    *,
    phase: str,
    stream: Optional[str] = None,
    label: Optional[str] = None,
    exc: Optional[BaseException] = None,
    level: str = "warning",
) -> None:
    """Structured log line(s) for profile / preference modal diagnostics."""
    lines: list[str] = [
        f"[AUTH][profile] ctx phase={phase!r} url={page.url}",
        f"  {_profile_dialog_count_summary(page)}",
    ]
    if stream is not None:
        lines.append(f"  stream={stream!r}")
    if label is not None:
        lines.append(f"  label_try={label!r}")
    if popup is not None:
        try:
            lines.append(
                f"  preference_modal={_popup_is_change_your_preference(popup)}"
            )
        except Exception as err:
            lines.append(f"  preference_modal_err={err!r}")
        for pill, exact in (("JEE", True), ("JEE", False)):
            try:
                c = popup.get_by_text(pill, exact=exact).count()
                lines.append(f"  get_by_text({pill!r}, exact={exact}).count={c}")
            except Exception as err:
                lines.append(f"  get_by_text_count_err pill={pill!r} exact={exact}: {err!r}")
        if label:
            try:
                c = popup.get_by_text(label, exact=True).count()
                lines.append(f"  get_by_text(label, exact=True).count={c}")
            except Exception as err:
                lines.append(f"  label_exact_count_err={err!r}")
        try:
            raw = popup.inner_text(timeout=5_000) or ""
            lines.append(f"  dialog_text={_excerpt_one_line(raw)!r}")
        except Exception as err:
            lines.append(f"  inner_text_err={err!r}")
    if exc is not None:
        lines.append(f"  exception={exc!r}")
    msg = "\n".join(lines)
    if level == "debug":
        logging.debug(msg)
    elif level == "info":
        logging.info(msg)
    else:
        logging.warning(msg)


def _write_profile_debug_bundle(
    page: Page,
    popup: Optional[Locator],
    tag: str,
    exc: Optional[BaseException],
) -> None:
    if not _profile_debug_verbose():
        return
    reports = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports, exist_ok=True)
    ts = int(time.time())
    stub = os.path.join(reports, f"profile-debug-{tag}-{ts}")
    chunks: list[str] = [
        f"tag={tag}",
        f"timestamp={ts}",
        f"url={page.url}",
        f"exception={exc!r}",
        "",
        _profile_dialog_count_summary(page),
        "",
    ]
    if popup is not None:
        chunks.append("--- dialog inner_text ---\n")
        try:
            chunks.append((popup.inner_text(timeout=10_000) or "")[:80_000])
        except Exception as err:
            chunks.append(f"(inner_text failed: {err})")
    txt_path = stub + ".txt"
    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(chunks))
        logging.info("[AUTH][profile] Wrote debug transcript: %s", txt_path)
    except Exception as err:
        logging.warning("[AUTH][profile] Could not write transcript: %s", err)
    try:
        png_path = stub + ".png"
        page.screenshot(path=png_path, full_page=True)
        logging.info("[AUTH][profile] Wrote debug screenshot: %s", png_path)
    except Exception as err:
        logging.warning("[AUTH][profile] Screenshot failed: %s", err)


def _popup_is_change_your_preference(popup: Locator) -> bool:
    """allen.in profile editor uses a titled modal with pill rows (Stream / Class / Board)."""
    try:
        return "change your preference" in (popup.inner_text(timeout=3_000) or "").lower()
    except Exception:
        return False


def _click_preference_modal_pill(popup: Locator, label: str) -> None:
    """
    Click a pill in the *Change your preference* modal by exact text match.

    Tries three paths in order:
      1. ``get_by_text(exact=True)`` scoped to the dialog
      2. ``role=radio`` scoped to the dialog
      3. Page-level ``get_by_text(exact=True)`` (when dialog scope is body)

    Set ``WATCHDOG_PROFILE_DEBUG=1`` for verbose logs + ``reports/profile-debug-*``
    on failure.
    """
    pg = _locator_page(popup)
    opt_ms = int(os.environ.get("WATCHDOG_PROFILE_OPTION_MS", "15000"))
    errors: list[str] = []

    # 1. Exact text inside dialog scope
    try:
        hit = popup.get_by_text(label, exact=True).first
        hit.wait_for(state="visible", timeout=opt_ms)
        hit.scroll_into_view_if_needed(timeout=5_000)
        hit.click(timeout=min(10_000, opt_ms))
        logging.debug("[AUTH][profile] pill click ok (exact text) label=%r", label)
        return
    except Exception as exc:
        errors.append(f"exact_text:{exc!r}")

    # 2. Radio role inside dialog scope
    try:
        popup.get_by_role(
            "radio", name=re.compile(rf"^\s*{re.escape(label)}\s*$", re.I)
        ).first.click(timeout=min(10_000, opt_ms))
        logging.debug("[AUTH][profile] pill click ok (radio role) label=%r", label)
        return
    except Exception as exc:
        errors.append(f"radio:{exc!r}")

    # 3. Page-level fallback (dialog scope is body or portal wrapper)
    if pg is not None:
        try:
            pg.get_by_text(label, exact=True).first.click(timeout=min(10_000, opt_ms))
            logging.debug("[AUTH][profile] pill click ok (page-level) label=%r", label)
            return
        except Exception as exc:
            errors.append(f"page_level:{exc!r}")

    merged = "; ".join(errors)
    if pg is not None:
        _log_profile_change_context(
            pg, popup, phase="pill_failed", label=label, exc=RuntimeError(merged)
        )
        _write_profile_debug_bundle(
            pg, popup,
            f"pill-fail-{re.sub(r'[^a-zA-Z0-9_-]+', '_', label)[:40]}",
            RuntimeError(merged),
        )
    raise RuntimeError(f"[AUTH] Could not click preference pill {label!r} ({merged})")


def _select_stream_in_change_flow(page: Page, stream: str) -> None:
    """Click the stream pill in the *Change your preference* modal."""
    label = PROFILE_STREAM_LABELS[stream]
    popup: Optional[Locator] = None
    try:
        popup = _active_profile_dialog(page)
        _click_preference_modal_pill(popup, label)
    except Exception as exc:
        # On failure: log dialog text so we know what was actually rendered.
        try:
            tail = _active_profile_dialog(page)
            excerpt = _excerpt_one_line(tail.inner_text(timeout=5_000) or "", 900)
            logging.error(
                "[AUTH][profile] stream_select failed stream=%r label=%r "
                "dialog=%r exc=%r",
                stream, label, excerpt, exc,
            )
        except Exception:
            logging.error(
                "[AUTH][profile] stream_select failed stream=%r label=%r "
                "exc=%r (dialog text unavailable)",
                stream, label, exc,
            )
        _write_profile_debug_bundle(page, popup, f"stream-fail-{stream}", exc)
        raise RuntimeError(
            f"[AUTH] Could not select stream {stream!r} (label={label!r}): {exc!r}"
        ) from exc


def _wait_for_board_pills_after_class_change(page: Page, board_fragment: str) -> None:
    """
    After picking **Class**, the *Board* row is already visible on the
    *Change your preference* modal (allen.in renders all three rows at once).
    This function waits until a pill matching ``board_fragment`` is visible so
    we do not click a stale node.
    """
    frag = board_fragment.strip()
    if not frag:
        return
    settle_s = float(os.environ.get("WATCHDOG_PROFILE_AFTER_CLASS_S", "0.35"))
    time.sleep(settle_s)
    budget_ms = int(os.environ.get("WATCHDOG_PROFILE_BOARD_READY_MS", "8000"))
    deadline = time.time() + budget_ms / 1000.0
    pattern = re.compile(re.escape(frag), re.I)
    while time.time() < deadline:
        try:
            popup = _active_profile_dialog(page)
            if not _popup_is_change_your_preference(popup):
                return
            try:
                pill = popup.get_by_text(frag, exact=True).first
                if pill.is_visible(timeout=500):
                    return
            except Exception:
                pass
            cell = popup.locator(
                "button, a, div[role='button'], span, [role='radio'], label"
            ).filter(has_text=pattern).first
            if cell.is_visible(timeout=500):
                return
        except Exception:
            pass
        time.sleep(0.1)
    logging.warning(
        "[AUTH][profile] Board pill %r may not be visible after class change; "
        "continuing — increase WATCHDOG_PROFILE_BOARD_READY_MS if clicks miss.",
        frag,
    )


def _click_profile_wizard_save(page: Page) -> None:
    popup = _active_profile_dialog(page)
    for name in ("Save", "Update", "Confirm", "Apply", "Submit", "Done", "Continue"):
        try:
            b = popup.get_by_role(
                "button", name=re.compile(rf"^\s*{re.escape(name)}\s*$", re.I)
            )
            if b.count() == 0:
                continue
            cell = b.first
            if not cell.is_visible(timeout=800):
                continue
            cell.click(timeout=5_000)
            return
        except Exception:
            continue
    try:
        popup.locator("button[type='submit']").first.click(timeout=5_000)
        return
    except Exception:
        pass
    raise RuntimeError("[AUTH] Could not find Save/Confirm on profile Change dialog.")


def _wait_for_class_pills_after_stream_change(page: Page, class_fragment: str) -> None:
    """
    After choosing **Stream**, the *Class* row is rebuilt (6–10 vs 11/12, etc.).
    Wait until a matching class pill exists so we do not click stale DOM.
    """
    frag = class_fragment.strip()
    if not frag:
        return
    settle_s = float(os.environ.get("WATCHDOG_PROFILE_AFTER_STREAM_S", "0.55"))
    time.sleep(settle_s)
    try:
        popup = _active_profile_dialog(page)
    except Exception:
        return
    if not _popup_is_change_your_preference(popup):
        return
    budget_ms = int(os.environ.get("WATCHDOG_PROFILE_CLASS_READY_MS", "12000"))
    deadline = time.time() + budget_ms / 1000.0
    pattern = re.compile(re.escape(frag), re.I)
    while time.time() < deadline:
        try:
            popup = _active_profile_dialog(page)
            if not _popup_is_change_your_preference(popup):
                return
            try:
                pill = popup.get_by_text(frag, exact=True).first
                if pill.is_visible(timeout=600):
                    return
            except Exception:
                pass
            cell = popup.locator(
                "button, a, div[role='button'], span, [role='radio'], label"
            ).filter(has_text=pattern).first
            if cell.is_visible(timeout=600):
                return
        except Exception:
            pass
        time.sleep(0.12)
    logging.warning(
        "[AUTH] Class pills may not have appeared after stream change (fragment=%r); "
        "continuing — increase WATCHDOG_PROFILE_CLASS_READY_MS if clicks miss.",
        frag,
    )


def run_profile_change_flow(page: Page, stream: str) -> None:
    """
    Run the *Change your preference* modal flow **in strict order**:

        1. Navigate to ``https://allen.in/profile``
        2. Click **Change**
        3. Select **Stream** pill  ← modal opens with current stream pre-selected
        4. Wait for **Class** row to reflect the new stream
        5. Select **Class** pill (``WATCHDOG_PROFILE_CLASS``, required for all streams)
        6. Wait for **Board** row (Classes 6-10 only)
        7. Select **Board** pill (Classes 6-10 only; ``WATCHDOG_PROFILE_BOARD``
           or **CBSE** by default)
        8. Click **Save** — only after all selections are confirmed

    Board is **only** selected when ``stream == "Classes610"``, matching the UI
    rule stated by the user: "board only if stream is Class 6-10."

    Env vars:
        WATCHDOG_PROFILE_CLASS           Text of the Class pill (e.g. "11th", "8th")
        WATCHDOG_PROFILE_BOARD           Board pill text; default "CBSE" for Classes610
        WATCHDOG_PROFILE_AFTER_STREAM_S  Settle pause after stream click (default 0.55 s)
        WATCHDOG_PROFILE_CLASS_READY_MS  Poll budget for class pill after stream (default 12000)
        WATCHDOG_PROFILE_AFTER_CLASS_S   Settle pause after class click (default 0.35 s)
        WATCHDOG_PROFILE_BOARD_READY_MS  Poll budget for board pill after class (default 8000)
    """
    if stream not in PROFILE_STREAM_LABELS:
        raise ValueError(
            f"Unknown stream '{stream}'. Valid options: {list(PROFILE_STREAM_LABELS)}"
        )

    # ── Step 1 + 2: navigate to /profile and open Change modal ──────────────
    logging.info("[AUTH][profile] Starting change flow: stream=%s", stream)
    _goto_spa_no_networkidle(page, PROFILE_PAGE_URL)
    time.sleep(0.3)
    _dismiss_optional_overlays(page)
    _open_profile_change_modal(page)

    # ── Step 3: select stream ────────────────────────────────────────────────
    logging.info("[AUTH][profile] Step 3 — selecting stream: %s", stream)
    _select_stream_in_change_flow(page, stream)
    logging.info("[AUTH][profile] Stream selected: %s", stream)

    # ── Step 4 + 5: wait for class pills, then select class ──────────────────
    cls = os.environ.get("WATCHDOG_PROFILE_CLASS", "").strip()
    if cls:
        logging.info("[AUTH][profile] Step 4 — waiting for class pills...")
        _wait_for_class_pills_after_stream_change(page, cls)
        logging.info("[AUTH][profile] Step 5 — selecting class: %s", cls)
        _click_preference_modal_pill(_active_profile_dialog(page), cls)
        logging.info("[AUTH][profile] Class selected: %s", cls)
    else:
        logging.info(
            "[AUTH][profile] WATCHDOG_PROFILE_CLASS not set — skipping class selection"
        )
        time.sleep(0.35)

    # ── Step 6 + 7: board (Classes610 only) ─────────────────────────────────
    if stream == "Classes610":
        brd = os.environ.get("WATCHDOG_PROFILE_BOARD", "CBSE").strip()
        logging.info("[AUTH][profile] Step 6 — waiting for board pills (board=%s)...", brd)
        _wait_for_board_pills_after_class_change(page, brd)
        logging.info("[AUTH][profile] Step 7 — selecting board: %s", brd)
        try:
            _click_preference_modal_pill(_active_profile_dialog(page), brd)
            logging.info("[AUTH][profile] Board selected: %s", brd)
        except Exception as exc:
            logging.warning(
                "[AUTH][profile] Board selection %r failed (continuing to Save): %s",
                brd, exc,
            )
    else:
        logging.info(
            "[AUTH][profile] Board step skipped (only applies to Classes610, got %s)",
            stream,
        )

    # ── Step 8: Save ─────────────────────────────────────────────────────────
    logging.info("[AUTH][profile] Step 8 — clicking Save")
    _click_profile_wizard_save(page)
    try:
        page.wait_for_load_state("load", timeout=30_000)
    except Exception:
        pass
    time.sleep(0.4)
    logging.info(
        "[AUTH][profile] Change flow complete: stream=%s class=%r board=%r url=%s",
        stream,
        cls or "(not set)",
        os.environ.get("WATCHDOG_PROFILE_BOARD", "CBSE") if stream == "Classes610" else "(N/A)",
        page.url,
    )


def _auth_debug_screenshot(page: Page, tag: str) -> None:
    if os.environ.get("WATCHDOG_AUTH_DEBUG", "").lower() not in ("1", "true", "yes"):
        return
    reports = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(reports, exist_ok=True)
    path = os.path.join(reports, f"auth-debug-{tag}-{int(time.time())}.png")
    try:
        page.screenshot(path=path, full_page=True)
        logging.info("[AUTH] Debug screenshot written: %s", path)
    except Exception as exc:
        logging.warning("[AUTH] Debug screenshot failed: %s", exc)


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------

def _load_credentials() -> dict:
    """
    Load test account credentials.
    Priority: WATCHDOG_TEST_FORM_ID / WATCHDOG_TEST_PASSWORD env vars,
    then test_credentials.json (gitignored, local dev only).
    """
    form_id  = os.environ.get("WATCHDOG_TEST_FORM_ID", "").strip()
    password = os.environ.get("WATCHDOG_TEST_PASSWORD", "").strip()
    if form_id and password:
        logging.debug("[AUTH] Using credentials from env vars.")
        return {"form_id": form_id, "password": password}

    creds_path = os.path.join(os.path.dirname(__file__), "test_credentials.json")
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            "No test credentials found. Set WATCHDOG_TEST_FORM_ID and "
            "WATCHDOG_TEST_PASSWORD env vars, or create test_credentials.json "
            "(see test_credentials.example.json)."
        )
    with open(creds_path) as f:
        creds = json.load(f)
    logging.debug("[AUTH] Using credentials from test_credentials.json.")
    return creds


# ---------------------------------------------------------------------------
# AuthSession
# ---------------------------------------------------------------------------

class AuthSession:
    """
    Manages a single authenticated browser context for WatchDog.

    Typical usage — one session shared across all stream profiles::

        session = AuthSession(context)
        session.login()

        for stream in ["JEE", "NEET", "Classes610"]:
            session.switch_profile(stream)
            # scraper runs here against context ...

        session.close()
    """

    def __init__(self, context: BrowserContext) -> None:
        self.context   = context
        self.page: Optional[Page] = None
        self._creds    = _load_credentials()
        self._logged_in = False

    def _auth_trace(self, attempt: int, step: str) -> None:
        if self.page is None or self.page.is_closed():
            logging.info("[AUTH][trace] attempt=%s step=%s page=closed", attempt, step)
            return
        snap = _auth_ui_snapshot(self.page)
        logging.info(
            "[AUTH][trace] attempt=%s step=%s url=%s snapshot=%s",
            attempt,
            step,
            self.page.url,
            snap,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def login(self) -> None:
        """
        Log in via allen.in's modal Form ID flow:
          1. Navigate to homepage
          2. Click the nav "Login" button  → modal opens
          3. Click "Continue with Form ID" → form_id + password inputs appear
          4. Fill credentials and submit
          5. Confirm login by checking nav "Login" button is gone

        Raises RuntimeError if login cannot be confirmed after 3 attempts.
        """
        logging.info("[AUTH] Starting login...")
        if self.page is None or self.page.is_closed():
            self.page = self.context.new_page()

        for attempt in range(1, 4):
            last_step = "init"
            try:
                # Step 1 — land on homepage (avoid networkidle — see _goto_spa_no_networkidle)
                last_step = "goto_home"
                _goto_spa_no_networkidle(self.page, BASE_URL)
                logging.info(
                    "[AUTH] Waiting %.1fs for late homepage popup…",
                    POST_LOAD_LATE_POPUP_SEC,
                )
                time.sleep(POST_LOAD_LATE_POPUP_SEC)
                last_step = "dismiss_overlays"
                _dismiss_optional_overlays(self.page)
                self._auth_trace(attempt, last_step)

                if attempt > 1:
                    # Clear a stuck modal / overlay from a previous failed attempt
                    for _ in range(2):
                        self.page.keyboard.press("Escape")
                        time.sleep(0.2)

                # Step 2 — open the login modal.
                # allen.in pre-renders modal buttons in the DOM (hidden) — there are
                # TWO instances of each modal button (desktop + mobile). We must:
                #   a) wait for the nav Login button to be visible before clicking it
                #   b) wait for Form ID entry in the modal to become VISIBLE before
                #      clicking — allow extra time for hydration in headless mode.
                last_step = "nav_login_click"
                nav_btn_loc = self.page.locator(NAV_LOGIN_BUTTON)
                nav_btn_loc.first.wait_for(state="visible", timeout=15_000)
                nav_btn_loc.first.click(timeout=15_000)
                logging.info("[AUTH] Nav Login button clicked.")
                self._auth_trace(attempt, last_step)

                last_step = "wait_login_drawer"
                login_drawer = login_drawer_locator(self.page)
                self._auth_trace(attempt, last_step)

                # Step 3 — first *visible* + *enabled* Continue-with-Form-ID (skip hidden duplicates).
                last_step = "click_form_id_flow"
                logging.info(
                    "[AUTH] Polling for visible Continue-with-Form-ID (budget=%sms)…",
                    _form_id_flow_budget_ms(),
                )
                click_visible_form_id_flow_button(login_drawer)
                time.sleep(0.5)  # allow form transition animation
                logging.info("[AUTH] Form ID flow selected (visible Continue-with-Form-ID clicked).")
                self._auth_trace(attempt, last_step)

                # Step 4–6 — credential panel (picker controls may have unmounted).
                last_step = "resolve_credentials_panel"
                time.sleep(0.35)
                scope = login_credentials_panel_locator(self.page)
                self._auth_trace(attempt, last_step)

                last_step = "fill_form_id"
                fill_first_visible_in_scope(
                    scope,
                    FORM_ID_FIELD_SELECTORS,
                    self._creds["form_id"],
                    what="form id field",
                )

                last_step = "fill_password"
                time.sleep(0.2)
                fill_first_visible_in_scope(
                    scope,
                    (PASSWORD_INNER,),
                    self._creds["password"],
                    what="password field",
                )

                last_step = "submit"
                click_first_visible_submit_in_scope(scope)
                try:
                    self.page.wait_for_load_state("load", timeout=30_000)
                except Exception:
                    pass
                time.sleep(0.5)
                self._auth_trace(attempt, last_step)

                # Step 7 — confirm login
                last_step = "confirm_logged_in"
                if self._is_logged_in():
                    self._logged_in = True
                    logging.info("[AUTH] Login confirmed. URL: %s", self.page.url)
                    return

                logging.warning(
                    "[AUTH] Login attempt %d/3 not confirmed. URL: %s",
                    attempt, self.page.url,
                )
                self._auth_trace(attempt, last_step)
                time.sleep(3)

            except Exception as exc:
                logging.warning("[AUTH] Login attempt %d/3 raised at %s: %s", attempt, last_step, exc)
                self._auth_trace(attempt, f"error_after_{last_step}")
                _auth_debug_screenshot(self.page, f"a{attempt}-{last_step}")
                time.sleep(3)

        raise RuntimeError(
            "[AUTH] Login failed after 3 attempts. "
            "Check selectors in auth_session.py and run "
            "scripts/discover_auth_selectors.py to inspect the live page."
        )

    def switch_profile(self, stream: str) -> None:
        """
        Switch stream (and optionally class / board) via ``/profile`` → Change.

        Strict order: **stream → (wait) → class → (wait) → board** (board only
        for ``Classes610``, default **CBSE**) → **Save**. JEE / NEET skip board.

        Args:
            stream: One of "JEE", "NEET", "Classes610"
        """
        if stream not in PROFILE_STREAM_LABELS:
            raise ValueError(
                f"Unknown stream '{stream}'. Valid options: {list(PROFILE_STREAM_LABELS)}"
            )
        if not self._logged_in:
            raise RuntimeError(
                "[AUTH] Cannot switch profile — not logged in. Call login() first."
            )

        # Re-check session before switching
        self._ensure_session()
        page = self.page
        assert page is not None

        logging.info("[AUTH] Switching profile via /profile Change flow: stream=%s", stream)
        run_profile_change_flow(page, stream)
        logging.info("[AUTH] Profile switched to %s. URL: %s", stream, page.url)

    def close(self) -> None:
        """Close the auth page (not the context — that's the caller's responsibility)."""
        if self.page and not self.page.is_closed():
            try:
                self.page.close()
            except Exception:
                pass
        self._logged_in = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_logged_in(self) -> bool:
        """
        True when the nav Login CTA is not visible and either a positive
        logged-in chrome signal matches, or (by default) we infer success from
        the nav CTA alone. Set WATCHDOG_AUTH_STRICT_SUCCESS=1 to require a
        positive selector match.
        """
        if self.page is None:
            return False
        try:
            nav_btn = self.page.query_selector(NAV_LOGIN_STILL_VISIBLE)
            if nav_btn and nav_btn.is_visible():
                return False
        except Exception:
            return False

        strict = os.environ.get("WATCHDOG_AUTH_STRICT_SUCCESS", "").lower() in (
            "1",
            "true",
            "yes",
        )
        for sel in LOGGED_IN_POSITIVE_SELECTORS:
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible(timeout=600):
                    logging.debug("[AUTH] Logged-in check: positive match %r", sel)
                    return True
            except Exception:
                continue

        if strict:
            logging.warning(
                "[AUTH] Strict logged-in check failed: nav login hidden but no positive selector."
            )
            return False

        logging.debug(
            "[AUTH] Logged-in inferred (nav login hidden; no positive selector). "
            "Set WATCHDOG_AUTH_STRICT_SUCCESS=1 to require profile/logout UI."
        )
        return True

    def _ensure_session(self) -> None:
        """
        Detect session expiry and transparently re-login if needed.
        Called before each profile switch.
        """
        if self.page is None or self.page.is_closed():
            self._logged_in = False
            self.login()
            return

        try:
            current_url = self.page.url.lower()
        except Exception:
            self._logged_in = False
            self.login()
            return

        # Check URL for expiry signals
        url_expired = any(ind in current_url for ind in SESSION_EXPIRY_INDICATORS)

        # Lightweight check: try fetching a short text snippet from the body
        body_expired = False
        try:
            snippet = self.page.inner_text("body", timeout=5_000)[:500].lower()
            body_expired = any(ind in snippet for ind in SESSION_EXPIRY_INDICATORS)
        except Exception:
            pass

        if url_expired or body_expired:
            logging.warning("[AUTH] Session expiry detected — re-logging in.")
            self._logged_in = False
            self.login()
