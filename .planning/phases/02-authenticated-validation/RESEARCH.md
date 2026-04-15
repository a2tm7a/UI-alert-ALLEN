# Phase 2 — Research Notes

**Date:** 2026-04-15

---

## Codebase Findings

### Database Schema (current)

```sql
CREATE TABLE runs (
    run_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE courses (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER REFERENCES runs(run_id),
    base_url       TEXT,
    course_name    TEXT,
    cta_link       TEXT,
    price          TEXT,
    pdp_price      TEXT,
    cta_status     TEXT,
    is_broken      INTEGER DEFAULT 0,
    price_mismatch INTEGER DEFAULT 0,
    viewport       TEXT DEFAULT 'desktop',
    timestamp      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Changes needed for Phase 2:** Add `mode TEXT NOT NULL DEFAULT 'guest'` and `profile TEXT` (nullable) to `runs`. No changes to `courses` or other tables — all per-profile context is inherited through `run_id`.

### Module Structure

| Module | Role | Phase 2 impact |
|--------|------|----------------|
| `scraper.py` | `ScraperEngine` — orchestrates the full run | Add auth loop after guest run |
| `handlers.py` | `BasePageHandler` + `HomepageHandler`, `PLPHandler`, `StreamHandler` | No changes — handlers are auth-agnostic |
| `database.py` | `DatabaseManager` — SQLite CRUD | Update `create_run()` to accept `mode` + `profile` |
| `validation_service.py` | `ValidationService` — validates courses by `run_id` | No changes needed |
| `report_generator.py` | `ReportGenerator` — scoped to `run_id` | Minor: include `mode`/`profile` in header + filename |
| `email_service.py` | `EmailService` — SMTP email with report | Update env var names; include profile in subject line |
| `cache.py` | `PdpCache`, `ProgressTracker` | Can be shared across runs or isolated per profile |

### Env Var Support (current state)

`EmailService` already has partial env var support via `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_HOST`, `EMAIL_PORT`. These need to be aliased to the `WATCHDOG_SMTP_*` prefix for consistency.

No env var support exists yet for test account credentials.

### ScraperEngine.run() Flow (current)

```
create_run()  →  [desktop, mobile] parallel  →  validate  →  re-QC  →  report  →  email
```

Phase 2 extends this to:

```
guest run (existing flow)
  ↓
for each profile in [JEE, NEET, Classes610]:
    create_run(mode='authenticated', profile=profile_key)
    login() + switch_profile(stream)
    [desktop, mobile] parallel  →  validate  →  re-QC  →  report  →  email
    ↓ (next profile, same session re-used via switch_profile)
logout / close context
```

### handlers.py patterns to follow

- All env config uses `_env_int()`, `_env_bool()`, `_env_str()` helpers (lines 46–65)
- New env vars for auth should use the same helpers, prefixed `WATCHDOG_`
- `BasePageHandler.__init__` takes `page, run_id, db, pdp_cache, recheck_cache` — no auth coupling, which is correct

---

## allen.in Live Site (unverified — investigation required)

The live site was not accessible during research (network blocked in sandbox). The following are **assumptions** to be validated during implementation:

| Item | Assumption | How to verify |
|------|-----------|---------------|
| Login URL | `https://allen.in/sign-in` or modal on homepage | Navigate and check redirect / modal trigger |
| Form selectors | Standard `input[name="username"]` / `input[name="password"]` or phone/email field | Inspect DOM with Playwright `page.content()` snapshot |
| Stream switcher location | Nav bar dropdown or profile settings page | Inspect post-login DOM |
| Switch reloads page | Yes (confirmed by user) | Use `page.wait_for_load_state("networkidle")` |
| CAPTCHA | Possible reCAPTCHA v3 (invisible) | Check for `grecaptcha` in page JS |
| Session indicator | Cookie or localStorage `auth_token` / `user_session` | Check `context.cookies()` after login |

**Required discovery step in implementation:** Before writing the main auth loop, the implementation agent must navigate the live site, dump the login form HTML, and capture the exact selectors. These should be stored as constants in `auth_session.py`.

---

## Secrets Audit (R-23)

| Secret | Current storage | Target |
|--------|----------------|--------|
| SMTP host/port/user/pass | `email_config.json` (gitignored) | `WATCHDOG_SMTP_HOST`, `WATCHDOG_SMTP_PORT`, `WATCHDOG_SMTP_USER`, `WATCHDOG_SMTP_PASSWORD` |
| Email from/to/send_on | `email_config.json` | `WATCHDOG_EMAIL_FROM`, `WATCHDOG_EMAIL_TO`, `WATCHDOG_SEND_ON` |
| Test account form_id | `test_credentials.json` (gitignored) | `WATCHDOG_TEST_FORM_ID` |
| Test account password | `test_credentials.json` (gitignored) | `WATCHDOG_TEST_PASSWORD` |

Both JSON files remain as gitignored local fallbacks. The env vars take precedence. `.example` files are the committed reference.

---

## Risk Notes

- **Bot detection on login:** allen.in may use CAPTCHA or rate-limiting on the login endpoint. Playwright stealth is already applied to the scraper context (`STEALTH.apply_stealth_sync`). The same stealth setup should be applied to the authenticated browser context.
- **Session expiry mid-run:** Each profile pass can take 5–15 min. Sessions may expire. `AuthSession` must detect expiry (redirect to login page, 401, or known error text) and re-login transparently.
- **Test account enrollment:** If the test account becomes enrolled in courses, `CTA_MISSING` will fire. Per product decision, this is correct behaviour — keep account unenrolled.
- **PdpCache sharing:** The guest run populates `PdpCache`. Authenticated runs hitting the same PDPs may get different results (logged-in CTAs). A fresh `PdpCache` per authenticated profile run is safer to avoid stale guest-mode PDP data bleeding in.
