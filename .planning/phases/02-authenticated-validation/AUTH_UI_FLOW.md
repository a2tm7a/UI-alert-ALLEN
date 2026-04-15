# allen.in — Login UI flow (automation contract)

Single source of truth for what WatchDog **assumes** about the site, how that maps to code, and what is **not** automated.

**Related code:** [`auth_session.py`](../../../auth_session.py), [`scripts/discover_auth_selectors.py`](../../../scripts/discover_auth_selectors.py)

---

## Target flow (Form ID branch — automated)

| Step | State / screen | User or bot action | URL / DOM change | Automation (`AuthSession.login`) |
|------|----------------|-------------------|------------------|----------------------------------|
| 0 | Homepage loaded | (none) | `allen.in` / SPA shell | `_goto_spa_no_networkidle`, post-load sleep, `_dismiss_optional_overlays` |
| 1 | Homepage with nav | Optional promos dismissed | Nav visible | Waits + overlay handling |
| 2 | Login modal closed | Click **Login** (`loginCtaButton`) | Modal opens | Click `NAV_LOGIN_BUTTON` |
| 3 | Modal — method picker | Click **Continue with Form ID** (inside login drawer only) | Form ID + password fields | `login_drawer_locator` → poll visible `FormIdLoginButtonWeb` / role name |
| 4 | Modal — credentials | Enter Form ID + password | Fields filled | `login_credentials_panel_locator` (dialog that **has** form/password inputs — not the picker dialog) + **visible-first** fill |
| 5 | Modal — submit | Submit | Navigation or SPA update | `click_first_visible_submit_in_scope` + `wait_for_load_state` |
| 6 | Logged in | (none) | Nav **Login** CTA hidden; optional profile / Log out UI | `_is_logged_in`: nav hidden + optional positive selectors |

Update this table after each major allen.in UI change (copy DevTools `data-testid` and labels into **Visible primary actions**).

---

## Profile change — stream, class, board (`AuthSession.switch_profile`)

After login, WatchDog does **not** use homepage nav links to switch stream. It follows the same path a user would on the profile page:

**Modal behavior (human + bot):** After **Change**, the popup shows the **current** stream as the selected pill. To switch, click the **new** stream pill. The **Class** row then **updates** for that stream (e.g. 6th–10th vs 11th/12th); only **after** that repaint should you pick class (and board if shown).

| Step | Screen | Action | Automation |
|------|--------|--------|------------|
| 0 | Any post-login URL | (none) | `_ensure_session` |
| 1 | Profile | Open `https://allen.in/profile` | `_goto_spa_no_networkidle(page, PROFILE_PAGE_URL)` |
| 2 | Profile | Dismiss promos if present | `_dismiss_optional_overlays` |
| 3 | Profile | Click **Change** | `PROFILE_CHANGE_BUTTON` (visible first control matching text *Change*) |
| 4 | Dialog | Select **target stream** pill | *Change your preference*: click the desired pill (**JEE** / **NEET** / **Class 6-10**) even if another stream was pre-selected |
| 5 | Dialog | Wait for **Class** row | `_wait_for_class_pills_after_stream_change` — settle + poll until `WATCHDOG_PROFILE_CLASS` matches a visible pill |
| 6 | Dialog | Select **class** (optional) | If `WATCHDOG_PROFILE_CLASS` is set, click that pill (exact text in preference modal, else substring match) |
| 7 | Dialog | Wait for **Board** row (Classes 6-10 only) | `_wait_for_board_pills_after_class_change` — settle + poll until board pill visible |
| 8 | Dialog | Select **Board** (Classes 6-10 only) | `WATCHDOG_PROFILE_BOARD` or **CBSE** by default. Board step **skipped entirely for JEE and NEET**. |
| 9 | Dialog | Click **Save** — only after all selections confirmed | `_click_profile_wizard_save` |

**Rule:** Save is clicked **only after** stream + class + board are all set. Board applies **only to `Classes610`**; JEE / NEET skip steps 7–8 entirely.

Tuning: `WATCHDOG_PROFILE_DIALOG_MS` (default 25000), `WATCHDOG_PROFILE_OPTION_MS` (default 15000), `WATCHDOG_PROFILE_AFTER_STREAM_S` (default 0.55), `WATCHDOG_PROFILE_CLASS_READY_MS` (default 12000), `WATCHDOG_PROFILE_AFTER_CLASS_S` (default 0.35), `WATCHDOG_PROFILE_BOARD_READY_MS` (default 8000).

---

## Branches we do **not** automate (document here when seen)

| Branch | Typical signal | WatchDog behavior |
|--------|----------------|-------------------|
| Mobile number + OTP | `submitOTPButton`, phone field | Not supported in headless; login fails with trace at “Form ID flow” step if that path is default |
| Username / email login | `usernameLoginButtonWeb` | Same — automation only enters **Form ID** path |
| CAPTCHA / device verify | iframe or challenge div | Not supported; use headed manual login or skip authenticated runs |
| Extra “Verify” after password | Unknown interstitial | Extend flow table + code once observed |

---

## Environment flags (debugging)

| Variable | Effect |
|----------|--------|
| `WATCHDOG_AUTH_DEBUG=1` | On login exception, write `reports/auth-debug-<step>-<timestamp>.png` |
| `WATCHDOG_AUTH_STRICT_SUCCESS=1` | `_is_logged_in` requires a **positive** indicator (profile / Log out text), not only “nav Login hidden” |
| `WATCHDOG_AUTH_MODAL_MS` | Max wait (ms) for Form ID entry control after opening modal (default 25000) |
| `WATCHDOG_FORM_ID_FLOW_MS` | Poll budget (ms) to find a **visible** Continue-with-Form-ID button and click it (default 10000); avoids waiting on a hidden duplicate |
| `WATCHDOG_CRED_FIELD_MS` | Poll budget (ms) for **visible** form-id / password / submit controls after the method picker (default 18000) |
| `WATCHDOG_PROFILE_CLASS` | Substring matched in the Change dialog when choosing **class** after stream (optional unless the UI requires it) |
| `WATCHDOG_PROFILE_BOARD` | Substring for **board**; if unset for `Classes610`, automation defaults to **CBSE** |
| `WATCHDOG_PROFILE_DIALOG_MS` | Max wait (ms) for the Change modal layer to become visible (default 25000) |
| `WATCHDOG_PROFILE_OPTION_MS` | Timeout (ms) when waiting for a stream/class/board tile to become visible (default 15000) |
| `WATCHDOG_PROFILE_AFTER_STREAM_S` | Seconds to sleep after stream click before polling for class pills (default 0.55) |
| `WATCHDOG_PROFILE_CLASS_READY_MS` | Max time (ms) to poll for the class pill after stream change (default 12000) |
| `WATCHDOG_PROFILE_DEBUG=1` | Verbose `[AUTH][profile]` logs; on pill/stream failures writes `reports/profile-debug-*.txt` (dialog `inner_text`) and `reports/profile-debug-*.png` (full page). Use with `python3 … 2>&1 \| tee run.log` to capture INFO lines. |

---

## Verification checklist (human)

1. `python3 -m pytest tests/test_auth_session.py` — offline behavior (`_is_logged_in`, `_ensure_session`); full suite: `python3 -m pytest tests/ -q`.
2. `HEADLESS=0 python3 scripts/discover_auth_selectors.py` with `WATCHDOG_TEST_*` or `test_credentials.json` — confirm modal steps and “Login success” line.
3. `python3 scraper.py` with the same credentials — grep logs for `[AUTH] Login confirmed` and `[AUTH][trace]` steps.
4. If failures persist, set `WATCHDOG_AUTH_DEBUG=1` and inspect `reports/auth-debug-*.png`; match the failing **step** in logs (`error_after_<step>`).
5. Optional: `WATCHDOG_AUTH_STRICT_SUCCESS=1` to require a positive logged-in selector (Log out / profile testids) before treating login as success.
