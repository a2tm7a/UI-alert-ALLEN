---
phase: 03-per-url-test-configuration
verified: 2026-04-15T00:00:00Z
status: human_needed
score: 15/15 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run live scrape against a results page URL that has CTA_MISSING opted out"
    expected: "No CTA_MISSING or PRICE_MISMATCH results appear in the generated report for that URL"
    why_human: "Requires a live Playwright scraping run against production URLs; cannot test without starting the full scraper pipeline"
---

# Phase 3: Per-URL Test Configuration Verification Report

**Phase Goal:** A configuration file defining which checks to run on which URLs — structured as a matrix where URLs are rows and checks are columns. Each URL can opt in/out of specific checks (e.g., URL A runs checks A, B, C, D; URL B runs checks A, B, E, F).
**Verified:** 2026-04-15
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `CheckConfig.load('config/url_checks.yaml')` parses the YAML file and returns a valid CheckConfig instance | ✓ VERIFIED | Smoke test: `c.version == 1`, `sorted(c.defaults.enabled) == ['CTA_BROKEN','CTA_MISSING','PRICE_MISMATCH']`, `c.url_count == 11`; `test_load_valid_config` passes |
| 2 | `CheckConfig.load('nonexistent.yaml')` returns a permissive default (all 3 checks enabled) and logs a WARNING | ✓ VERIFIED | `FileNotFoundError` handler at check_config.py:58–62; `test_load_missing_file` passes; WARNING logged via `logging.warning` |
| 3 | `CheckConfig.enabled_checks_for(url)` returns URL-specific check set when the URL is in config | ✓ VERIFIED | `enabled_checks_for` iterates `self.urls` with rstrip normalization (check_config.py:40–43); `test_url_override` passes |
| 4 | `CheckConfig.enabled_checks_for(url)` returns `defaults.enabled` set when URL is not in config | ✓ VERIFIED | Falls through loop to `return frozenset(self.defaults.enabled)` (check_config.py:44); `test_url_fallback_to_defaults` passes |
| 5 | URL trailing-slash normalization: `'https://allen.in/'` and `'https://allen.in'` resolve to the same config entry | ✓ VERIFIED | `rstrip('/')` on both lookup and config key (check_config.py:40,42); `test_trailing_slash_normalization` tests both directions and passes |
| 6 | Unknown check name in YAML logs a WARNING (contains the unknown name) and does not raise an exception | ✓ VERIFIED | `@field_validator("enabled")` computes `set(v) - KNOWN_CHECK_TYPES` and logs WARNING (check_config.py:20–24); `test_unknown_check_name_warns` with caplog assertion passes |
| 7 | `enabled: []` is accepted; `enabled_checks_for` returns an empty set; run continues | ✓ VERIFIED | No guard on empty list; `frozenset([]) == set()` (check_config.py:43); `test_empty_enabled_list_allowed` passes |
| 8 | All 7 pytest tests in `tests/test_check_config.py` pass | ✓ VERIFIED | `python3 -m pytest tests/test_check_config.py -x -q` → **7 passed in 0.07s** |
| 9 | `ValidationService.validate_course(course_data, check_config=cfg)` filters results to only those whose `type` is in `cfg.enabled_checks_for(base_url)` | ✓ VERIFIED | Filter logic at validation_service.py:52–56; `test_check_config_filtering` asserts CTA_BROKEN in and PRICE_MISMATCH out; passes |
| 10 | `ValidationService.validate_course(course_data, check_config=None)` returns all results unchanged (backward compat) | ✓ VERIFIED | `if check_config is None: return raw` (validation_service.py:52–53); `test_check_config_filtering` backward-compat branch asserts both types returned |
| 11 | `ValidationService.validate_all_courses(run_id=N, check_config=cfg)` propagates `check_config` to each `validate_course` call | ✓ VERIFIED | `issues = self.validate_course(course_data, check_config=check_config)` at validation_service.py:88 |
| 12 | `ScraperEngine.run()` loads `CheckConfig.load('config/url_checks.yaml')` once and passes it to both `validate_all_courses()` calls | ✓ VERIFIED | scraper.py:418 `check_config = CheckConfig.load(...)`, line 420 first pass, line 442 recheck pass |
| 13 | Results pages produce zero `CTA_MISSING` or `PRICE_MISMATCH` results when `config/url_checks.yaml` restricts them to `CTA_BROKEN` only | ✓ VERIFIED (automated) | Smoke test: `enabled_checks_for('https://allen.in/jee/results-2025') == frozenset({'CTA_BROKEN'})`; filter wiring confirmed; live E2E still requires human (see Human Verification) |
| 14 | All existing tests in `tests/test_validation_service.py` still pass (no regressions) | ✓ VERIFIED | `python3 -m pytest tests/test_validation_service.py -x -q` → **25 passed in 0.18s** |
| 15 | New test `test_check_config_filtering` passes | ✓ VERIFIED | `python3 -m pytest tests/test_validation_service.py::test_check_config_filtering -x -q` → **1 passed in 0.15s** |

**Score:** 15/15 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `constants.py` | `KNOWN_CHECK_TYPES` frozenset — single source of truth | ✓ VERIFIED | `KNOWN_CHECK_TYPES: frozenset = frozenset({"CTA_BROKEN", "CTA_MISSING", "PRICE_MISMATCH"})` at line 31 |
| `check_config.py` | `CheckConfig` Pydantic model + YAML loader | ✓ VERIFIED | 63 lines; `CheckConfig`, `UrlCheckSpec`, `yaml.safe_load`, `rstrip`, `FileNotFoundError` all present |
| `config/url_checks.yaml` | Per-URL check matrix with defaults + results/registration page overrides | ✓ VERIFIED | `version: 1`, 3 defaults, 11 URL entries (10 results pages + 1 registration page) |
| `tests/test_check_config.py` | 7 unit tests covering all CheckConfig behaviors | ✓ VERIFIED | 114 lines; 7 test functions confirmed; all pass |
| `validation_service.py` | `validate_course()` + `validate_all_courses()` with optional `check_config` | ✓ VERIFIED | `check_config` appears 8 times; `enabled_checks_for` wired at line 55; `Optional[Any]` with TYPE_CHECKING guard |
| `scraper.py` | `CheckConfig` loaded once in `run()`, passed to both `validate_all_courses()` calls | ✓ VERIFIED | Import at line 49; load at line 418; two call sites at lines 420 and 442 |
| `tests/test_validation_service.py` | `test_check_config_filtering` integration test | ✓ VERIFIED | Function at line 392; passes |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `check_config.py` | `config/url_checks.yaml` | `yaml.safe_load()` in `CheckConfig.load()` | ✓ WIRED | `with open(path, encoding="utf-8") as fh: data = yaml.safe_load(fh)` at check_config.py:55–56 |
| `check_config.py` | `constants.py` | `from constants import KNOWN_CHECK_TYPES` | ✓ WIRED | Import at check_config.py:11; used in `_warn_unknown_check_names` validator |
| `scraper.py` | `check_config.py` | `CheckConfig.load('config/url_checks.yaml')` in `ScraperEngine.run()` | ✓ WIRED | `from check_config import CheckConfig` at line 49; `CheckConfig.load(...)` at line 418 |
| `validation_service.py` | `check_config.py` | `check_config.enabled_checks_for(base_url)` in `validate_course()` | ✓ WIRED | `enabled = check_config.enabled_checks_for(base_url)` at line 55; TYPE_CHECKING guard at line 12 |
| `scraper.py` | `validation_service.py` | `validate_all_courses(run_id=run_id, check_config=check_config)` | ✓ WIRED | Both call sites at scraper.py:420 and 442 pass `check_config=check_config` |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `validation_service.py` | `enabled` (frozenset) | `check_config.enabled_checks_for(base_url)` → iterates `self.urls` loaded from YAML | Yes — real YAML data flowing through Pydantic model | ✓ FLOWING |
| `check_config.py` | `data` | `yaml.safe_load(fh)` reading real `config/url_checks.yaml` (11 URL entries) | Yes — real file read at runtime | ✓ FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `CheckConfig.load()` parses production YAML correctly | `python3 -c "from check_config import CheckConfig; c = CheckConfig.load('config/url_checks.yaml'); assert c.version == 1 and len(c.urls) == 11; print('OK')"` | `OK` | ✓ PASS |
| Results page returns only `CTA_BROKEN` | `python3 -c "...; assert c.enabled_checks_for('https://allen.in/jee/results-2025') == frozenset({'CTA_BROKEN'}); print('OK')"` | `frozenset({'CTA_BROKEN'})` | ✓ PASS |
| Non-configured URL returns full defaults | `python3 -c "...; assert c.enabled_checks_for('https://allen.in/jee') == frozenset({'CTA_BROKEN', 'CTA_MISSING', 'PRICE_MISMATCH'}); print('OK')"` | `frozenset({'CTA_BROKEN', 'CTA_MISSING', 'PRICE_MISMATCH'})` | ✓ PASS |
| Trailing-slash normalization | `python3 -c "...; assert c.enabled_checks_for('https://allen.in/jee/results-2025/') == frozenset({'CTA_BROKEN'}); print('OK')"` | `frozenset({'CTA_BROKEN'})` | ✓ PASS |
| All 238 tests pass (no regressions) | `python3 -m pytest tests/ -q` | `238 passed in 0.70s` | ✓ PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| REQ-config | 03-01-PLAN.md | Config file loading, URL-keyed check matrix, `CheckConfig` Pydantic model with YAML parsing, graceful missing-file fallback, unknown-name warnings, trailing-slash normalization | ✓ SATISFIED | 8/8 VALIDATION.md test IDs covered by passing pytest suite; `check_config.py` + `config/url_checks.yaml` + `tests/test_check_config.py` all verified |
| REQ-filter | 03-02-PLAN.md | Runtime filtering of `ValidationResult` objects by enabled check types per URL, wired through `ValidationService` and `ScraperEngine` | ✓ SATISFIED | `test_check_config_filtering` passes; both scraper.py call sites confirmed; 2/2 VALIDATION.md filter test IDs pass |

**Note:** No separate `REQUIREMENTS.md` file exists in `.planning/`. Requirement IDs `REQ-config` and `REQ-filter` are defined in `ROADMAP.md` (Phase 3 requirements field) and cross-referenced in `03-VALIDATION.md`. All requirement test IDs from the validation matrix are covered.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | None found |

No `TODO`, `FIXME`, `placeholder`, `return null`, or empty implementation patterns found in any Phase 3 modified files. `yaml.safe_load()` confirmed (not `yaml.load()`); T-03-01 mitigated. All threat mitigations from STRIDE register applied.

---

### Human Verification Required

#### 1. Live Scraping End-to-End: False-Positive Suppression on Results Pages

**Test:** Run `python watchdog.py` (or equivalent scrape trigger) against a results page URL (e.g. `https://allen.in/jee/results-2025`) that has `CTA_MISSING` and `PRICE_MISMATCH` opted out in `config/url_checks.yaml`.

**Expected:** The generated report and database contain zero `CTA_MISSING` or `PRICE_MISMATCH` issues for that URL. Only `CTA_BROKEN` (if any) appears.

**Why human:** Requires a full live Playwright browser scraping run against production URLs. Cannot be triggered without starting the scraper pipeline and real network access to allen.in. All automated layers (config loading, filter wiring, unit tests) have been verified; this is the final end-to-end smoke test.

---

### Gaps Summary

No gaps found. All 15 must-haves are verified through code inspection, unit tests, and behavioral spot-checks. The single outstanding item is a live end-to-end human verification test for false-positive suppression on results pages — the entire filtering stack is wired and tested; only a live scraping run can confirm the report output.

---

_Verified: 2026-04-15T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
