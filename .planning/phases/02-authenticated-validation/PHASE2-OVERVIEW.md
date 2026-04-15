# Phase 2 — Authenticated Validation · PLAN.md

**Project:** WatchDog (allen.in)
**Phase:** 2 — Authenticated Validation
**Status:** Ready to execute
**Created:** 2026-04-15

---

## Overview

Extend WatchDog to validate allen.in as a logged-in user across 3 stream profiles (JEE, NEET, Classes 6-10). Each profile gets its own `run_id`. Profiles run sequentially, sharing one browser session. Guest mode is unchanged.

**Execution order:** Plans 1 → 2 → 3 → 4 → 5 (each must pass before the next begins)

---

## Plan 1 — Secrets Management (R-23)

**Goal:** Move all secrets to environment variables. JSON config files become gitignored local fallbacks only.

### Tasks

**1.1 — Update `EmailService` to use `WATCHDOG_SMTP_*` env vars**

File: `email_service.py`

Replace the current partial env var support (`EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_HOST`, `EMAIL_PORT`) with the canonical `WATCHDOG_SMTP_*` prefix. Keep backward-compatible fallback to the old names so existing deployments don't break immediately.

New env var reading order (first non-empty wins):
```
WATCHDOG_SMTP_HOST      → smtp.host           (fallback: EMAIL_HOST, then smtp.gmail.com)
WATCHDOG_SMTP_PORT      → smtp.port           (fallback: EMAIL_PORT, then 587)
WATCHDOG_SMTP_USER      → smtp.username       (fallback: EMAIL_USERNAME)
WATCHDOG_SMTP_PASSWORD  → smtp.password       (fallback: EMAIL_PASSWORD)
WATCHDOG_EMAIL_FROM     → notification.from
WATCHDOG_EMAIL_TO       → notification.to     (comma-separated → list)
WATCHDOG_SEND_ON        → send_on             (always / errors / never)
```

**1.2 — Create `test_credentials.example.json`**

File: `test_credentials.example.json` (new, committed)

```json
{
  "form_id": "YOUR_TEST_ACCOUNT_FORM_ID",
  "password": "YOUR_TEST_ACCOUNT_PASSWORD"
}
```

Add a comment block at the top of `test_credentials.json` (gitignored local file) pointing to env vars:
```json
{
  "_comment": "Set WATCHDOG_TEST_FORM_ID and WATCHDOG_TEST_PASSWORD env vars instead of filling this file in production.",
  "form_id": "...",
  "password": "..."
}
```

**1.3 — Update `email_config.example.json`**

Update the existing `email_config.example.json` to document the new `WATCHDOG_SMTP_*` env var names alongside the JSON keys.

**1.4 — Update `.gitignore`**

Confirm both `email_config.json` and `test_credentials.json` are present. Add `*.env` and `.env` as a safety net.

**1.5 — Document env vars in `README.md`**

Add an "Environment Variables" section listing all `WATCHDOG_*` vars, their purpose, and defaults.

### Verification

- Run `python3 -c "from email_service import EmailService; e = EmailService(); print('OK')"` — should not raise.
- Set `WATCHDOG_SMTP_HOST=test.host` in the shell and confirm `EmailService` picks it up over the JSON value.

---

## Plan 2 — Database Schema Migration

**Goal:** Add `mode` and `profile` columns to the `runs` table without breaking existing data.

### Tasks

**2.1 — Update `DatabaseManager._init_db()`**

File: `database.py`

Change `CREATE TABLE IF NOT EXISTS runs` to include the new columns:

```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    mode       TEXT NOT NULL DEFAULT 'guest',
    profile    TEXT
);
```

**2.2 — Add migration for existing `scraped_data.db`**

In `_init_db()`, after the CREATE TABLE, add idempotent migration guards:

```python
for col_def in [
    "ALTER TABLE runs ADD COLUMN mode TEXT NOT NULL DEFAULT 'guest'",
    "ALTER TABLE runs ADD COLUMN profile TEXT",
]:
    try:
        conn.execute(col_def)
    except sqlite3.OperationalError:
        pass  # column already exists
```

**2.3 — Update `DatabaseManager.create_run()`**

Accept optional `mode: str = "guest"` and `profile: str | None = None` parameters:

```python
def create_run(self, mode: str = "guest", profile: str | None = None) -> int:
    with sqlite3.connect(self.db_name) as conn:
        cursor = conn.execute(
            "INSERT INTO runs (mode, profile) VALUES (?, ?)",
            (mode, profile),
        )
        run_id = cursor.lastrowid
        logging.info(f"Run #{run_id} started (mode={mode}, profile={profile or 'n/a'}).")
        return run_id
```

### Verification

- Delete `scraped_data.db`, run `python3 -c "from database import DatabaseManager; db = DatabaseManager(); rid = db.create_run('authenticated', 'JEE'); print(rid)"` — should print a run_id.
- Rerun the same command against the existing db (with old schema) — migration should apply and succeed without error.

---

## Plan 3 — AuthSession Module (R-20, R-21)

**Goal:** New `auth_session.py` module encapsulating all login and profile-switching logic. No scraping logic — only session lifecycle.

### Tasks

**3.1 — Discovery step (MUST run first)**

Before writing the final selectors, use Playwright to navigate allen.in and capture the login form HTML. Add this as a helper script `scripts/discover_auth_selectors.py`:

```python
"""
Run once to discover the allen.in login form structure.
Usage: python3 scripts/discover_auth_selectors.py
Prints the login page HTML and post-login page URL to stdout.
"""
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

STEALTH = Stealth()

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)  # visible for inspection
    context = browser.new_context()
    STEALTH.apply_stealth_sync(context)
    page = context.new_page()
    
    # Try known login URLs
    for url in ["https://allen.in/sign-in", "https://allen.in/login", "https://allen.in/"]:
        page.goto(url, wait_until="networkidle")
        print(f"\n=== {url} ===")
        print(f"Final URL: {page.url}")
        # Print all input elements
        inputs = page.query_selector_all("input")
        for inp in inputs:
            print(f"  input: name={inp.get_attribute('name')} id={inp.get_attribute('id')} type={inp.get_attribute('type')} placeholder={inp.get_attribute('placeholder')}")
        buttons = page.query_selector_all("button[type=submit], button:has-text('Sign'), button:has-text('Login'), button:has-text('login')")
        for btn in buttons:
            print(f"  button: text='{btn.inner_text()}' id={btn.get_attribute('id')}")
    
    browser.close()
```

Run this script and record the discovered selectors before implementing `AuthSession`.

**3.2 — Create `auth_session.py`**

File: `auth_session.py` (new module)

```python
"""
AuthSession — login and profile-switching for WatchDog authenticated mode.

Credentials are read from env vars:
    WATCHDOG_TEST_FORM_ID      — test account form_id / phone / email
    WATCHDOG_TEST_PASSWORD     — test account password

Fallback: test_credentials.json (gitignored, local dev only).
"""

import json
import logging
import os
import time
from typing import Optional

from playwright.sync_api import BrowserContext, Page

# ---------------------------------------------------------------------------
# Selectors — update after running scripts/discover_auth_selectors.py
# ---------------------------------------------------------------------------
LOGIN_URL          = "https://allen.in/sign-in"        # update if different
FORM_ID_SELECTOR   = "input[name='username']"          # update after discovery
PASSWORD_SELECTOR  = "input[type='password']"          # update after discovery
SUBMIT_SELECTOR    = "button[type='submit']"           # update after discovery
LOGIN_SUCCESS_URL  = "/dashboard"                       # update after discovery — URL fragment that confirms login

# Stream → selector mapping for the profile switcher
# Keys must match the profile keys used in ScraperEngine
STREAM_SELECTORS = {
    "JEE":        "...",   # update after discovery
    "NEET":       "...",   # update after discovery
    "Classes610": "...",   # update after discovery
}

SESSION_EXPIRY_INDICATORS = [
    "/sign-in",
    "/login",
    "session expired",
    "please log in",
]


def _load_credentials() -> dict:
    form_id  = os.environ.get("WATCHDOG_TEST_FORM_ID")
    password = os.environ.get("WATCHDOG_TEST_PASSWORD")
    if form_id and password:
        return {"form_id": form_id, "password": password}
    creds_path = os.path.join(os.path.dirname(__file__), "test_credentials.json")
    with open(creds_path) as f:
        return json.load(f)


class AuthSession:
    """
    Manages a single authenticated browser context for WatchDog.

    Usage:
        session = AuthSession(context)
        session.login()
        session.switch_profile("JEE")
        # ... run scraper tasks ...
        session.switch_profile("NEET")
        # ... run scraper tasks ...
    """

    def __init__(self, context: BrowserContext):
        self.context   = context
        self.page: Optional[Page] = None
        self.creds     = _load_credentials()
        self._logged_in = False

    def login(self) -> bool:
        """
        Navigate to the login page, fill credentials, submit, and verify.
        Returns True on success. Raises RuntimeError if login fails after retries.
        """
        logging.info("[AUTH] Logging in...")
        self.page = self.context.new_page()

        for attempt in range(3):
            try:
                self.page.goto(LOGIN_URL, wait_until="networkidle", timeout=30_000)
                self.page.fill(FORM_ID_SELECTOR, self.creds["form_id"])
                self.page.fill(PASSWORD_SELECTOR, self.creds["password"])
                self.page.click(SUBMIT_SELECTOR)
                self.page.wait_for_load_state("networkidle", timeout=30_000)

                if self._check_logged_in():
                    self._logged_in = True
                    logging.info(f"[AUTH] Login successful. URL: {self.page.url}")
                    return True

                logging.warning(f"[AUTH] Login attempt {attempt + 1}/3 — not confirmed. URL: {self.page.url}")
                time.sleep(3)

            except Exception as exc:
                logging.warning(f"[AUTH] Login attempt {attempt + 1}/3 failed: {exc}")
                time.sleep(3)

        raise RuntimeError("[AUTH] Login failed after 3 attempts. Check credentials and selectors.")

    def switch_profile(self, stream: str) -> None:
        """
        Switch the logged-in user's stream profile via the UI dropdown.
        Waits for page reload to complete before returning.

        Args:
            stream: One of "JEE", "NEET", "Classes610"
        """
        if stream not in STREAM_SELECTORS:
            raise ValueError(f"Unknown stream '{stream}'. Valid: {list(STREAM_SELECTORS)}")

        if not self._logged_in:
            raise RuntimeError("[AUTH] Cannot switch profile — not logged in.")

        self._check_session_expiry()

        logging.info(f"[AUTH] Switching profile to: {stream}")
        selector = STREAM_SELECTORS[stream]

        # Navigate to profile switcher (homepage or settings — update URL after discovery)
        self.page.goto("https://allen.in", wait_until="networkidle", timeout=30_000)
        self.page.click(selector)
        self.page.wait_for_load_state("networkidle", timeout=30_000)
        logging.info(f"[AUTH] Profile switched to {stream}. URL: {self.page.url}")

    def _check_logged_in(self) -> bool:
        """Return True if the current page indicates an active session."""
        url = self.page.url
        return LOGIN_SUCCESS_URL in url or not any(
            indicator in url.lower() for indicator in SESSION_EXPIRY_INDICATORS
        )

    def _check_session_expiry(self) -> None:
        """
        Detect session expiry and re-login if needed.
        Called before each profile switch.
        """
        if self.page is None:
            return
        current_url = self.page.url.lower()
        page_text   = self.page.inner_text("body") if self.page else ""

        expired = any(ind in current_url for ind in SESSION_EXPIRY_INDICATORS) or \
                  any(ind in page_text.lower() for ind in SESSION_EXPIRY_INDICATORS)

        if expired:
            logging.warning("[AUTH] Session expiry detected — re-logging in.")
            self._logged_in = False
            self.login()

    def close(self) -> None:
        if self.page:
            try:
                self.page.close()
            except Exception:
                pass
```

### Verification

- Run `python3 -c "from auth_session import AuthSession, _load_credentials; print(_load_credentials())"` — should print credentials without error.
- Unit test: mock the Playwright page and verify `_check_logged_in()` returns correct values for login/expiry URLs.

---

## Plan 4 — ScraperEngine Integration (R-09)

**Goal:** Wire authenticated mode into `ScraperEngine.run()`. After the guest run, loop through 3 stream profiles sequentially.

### Tasks

**4.1 — Add profile constants to `scraper.py`**

```python
AUTH_PROFILES = ["JEE", "NEET", "Classes610"]
```

**4.2 — Import `AuthSession` in `scraper.py`**

```python
from auth_session import AuthSession  # type: ignore[import]
```

**4.3 — Extend `ScraperEngine.run()` with authenticated loop**

After the existing guest run, validation, re-QC, and email steps complete, add:

```python
# -----------------------------------------------------------------------
# Authenticated mode — one run per stream profile
# -----------------------------------------------------------------------
logging.info("Starting authenticated runs (%d profiles)...", len(AUTH_PROFILES))

with sync_playwright() as p_auth:
    mobile_kwargs_auth = dict(p_auth.devices[MOBILE_DEVICE])
    auth_context = p_auth.chromium.launch(headless=True, args=launch_args).new_context(
        **{
            "viewport":  {"width": 1920, "height": 1080},
            "user_agent": DESKTOP_UA,
            "locale":    "en-IN",
        }
    )
    STEALTH.apply_stealth_sync(auth_context)
    session = AuthSession(auth_context)
    session.login()

    for profile in AUTH_PROFILES:
        logging.info("--- Authenticated run: %s ---", profile)
        session.switch_profile(profile)

        auth_run_id  = self.db.create_run(mode="authenticated", profile=profile)
        auth_cache   = PdpCache()  # fresh cache per profile — no guest-mode bleed

        viewport_configs_auth = [
            ("desktop", {
                "viewport":  {"width": 1920, "height": 1080},
                "user_agent": DESKTOP_UA,
                "locale":    "en-IN",
                "extra_http_headers": {"Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8"},
                # Reuse existing logged-in cookies from auth_context
                "storage_state": auth_context.storage_state(),
            }),
            ("mobile", {
                **mobile_kwargs_auth,
                "storage_state": auth_context.storage_state(),
            }),
        ]

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(
                    self._run_viewport, tasks, label, kwargs, auth_run_id, auth_cache
                ): label
                for label, kwargs in viewport_configs_auth
            }
            for future in as_completed(futures):
                label = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logging.error(f"[AUTH:{profile}] [{label.upper()}] Pass failed: {e}")

        # Validate + report for this profile
        auth_validator = ValidationService(self.db.db_name)
        auth_issues    = auth_validator.validate_all_courses(run_id=auth_run_id)
        auth_validator.log_results()

        auth_reporter = ReportGenerator(
            issues=auth_issues,
            recheck_issues=[],
            start_time=datetime.now(),
            run_id=auth_run_id,
            mode="authenticated",
            profile=profile,
        )
        auth_report_path = auth_reporter.save()
        logging.info(f"[AUTH:{profile}] Report saved: {auth_report_path}")

        email_svc = EmailService()
        email_svc.send_report(
            report_path=auth_report_path,
            summary=auth_validator.get_summary(),
            profile=profile,
        )

    session.close()
    auth_context.close()
```

> **Note on `storage_state`:** Playwright's `browser.new_context(storage_state=...)` lets a new context inherit cookies from an existing one. This is how authenticated viewports (desktop + mobile) share the same logged-in session without needing a second login.

### Verification

- Run `python3 scraper.py` against a test URL file with a single low-traffic page.
- Confirm 4 run_ids are created in SQLite (1 guest + 3 profiles).
- Confirm `mode` and `profile` columns are correctly populated.
- Confirm 4 report files are generated.

---

## Plan 5 — Reporting Updates

**Goal:** Update `ReportGenerator` and `EmailService` to include mode/profile context in filenames, headers, and email subjects.

### Tasks

**5.1 — Update `ReportGenerator`**

File: `report_generator.py`

- Add `mode: str = "guest"` and `profile: str | None = None` params to `__init__`.
- Update report filename: `report_YYYY-MM-DD_HH-MM-SS.md` → `report_YYYY-MM-DD_HH-MM-SS_guest.md` / `report_YYYY-MM-DD_HH-MM-SS_auth_JEE.md`
- Update `_section_header()` to include a "Mode" row: `Guest` or `Authenticated — JEE`.

**5.2 — Update `EmailService.send_report()`**

File: `email_service.py`

- Add optional `profile: str | None = None` param to `send_report()`.
- Update subject line: `WatchDog Report — 2026-04-15` → `WatchDog Report — 2026-04-15 [Guest]` / `WatchDog Report — 2026-04-15 [Auth: JEE]`.

### Verification

- Confirm report filenames contain the mode/profile suffix.
- Confirm email subject line includes the profile label.

---

## Acceptance Criteria

| Criterion | How to verify |
|-----------|--------------|
| 4 run_ids created per nightly job (1 guest + 3 profiles) | Check `SELECT run_id, mode, profile FROM runs` after a run |
| Guest run is unchanged in behaviour | Compare guest report against a pre-Phase-2 baseline |
| CTA_MISSING raised for "Continue Learning" cards | Manually inspect a profile where the test account is enrolled |
| Session expiry triggers re-login, not silent fallback | Mock expiry in `AuthSession._check_session_expiry()` test |
| Secrets sourced from env vars in production | Set only env vars (no JSON files) and confirm run completes |
| 4 separate report files with correct names | Check `reports/` directory after a full run |
| No guest-mode PDP cache bleed into auth runs | Confirm fresh `PdpCache()` per profile run in code review |

---

## Pre-Implementation Checklist

- [ ] Run `scripts/discover_auth_selectors.py` against the live allen.in site and record all selectors
- [ ] Update `LOGIN_URL`, `FORM_ID_SELECTOR`, `PASSWORD_SELECTOR`, `SUBMIT_SELECTOR`, `LOGIN_SUCCESS_URL` in `auth_session.py`
- [ ] Update `STREAM_SELECTORS` dict with actual CSS selectors for the stream switcher
- [ ] Confirm `WATCHDOG_TEST_FORM_ID` and `WATCHDOG_TEST_PASSWORD` env vars are set in the scheduled task
- [ ] Confirm the test account is NOT enrolled in any courses before the first authenticated run
