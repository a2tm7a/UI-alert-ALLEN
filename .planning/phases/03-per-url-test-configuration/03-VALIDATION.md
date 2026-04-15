---
phase: 3
slug: per-url-test-configuration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pytest.ini` (exists in root) |
| **Quick run command** | `python3 -m pytest tests/test_check_config.py -x -q` |
| **Full suite command** | `python3 -m pytest tests/ -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python3 -m pytest tests/test_check_config.py -x -q`
- **After every plan wave:** Run `python3 -m pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | REQ-config | T-03-01 | `yaml.safe_load()` used (not `yaml.load()`) | unit (Wave 0) | `python3 -m pytest tests/test_check_config.py --collect-only -q` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | REQ-config | T-03-03 | Unknown check name logs WARNING, no crash | unit | `python3 -m pytest tests/test_check_config.py::test_unknown_check_name_warns -xq` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | REQ-config | — | Missing config file falls back to all checks | unit | `python3 -m pytest tests/test_check_config.py::test_load_missing_file -xq` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | REQ-config | — | Valid YAML parsed and CheckConfig returned | unit | `python3 -m pytest tests/test_check_config.py::test_load_valid_config -xq` | ❌ W0 | ⬜ pending |
| 03-01-05 | 01 | 1 | REQ-config | — | URL-specific override returned correctly | unit | `python3 -m pytest tests/test_check_config.py::test_url_override -xq` | ❌ W0 | ⬜ pending |
| 03-01-06 | 01 | 1 | REQ-config | — | Unconfigured URL falls back to defaults | unit | `python3 -m pytest tests/test_check_config.py::test_url_fallback_to_defaults -xq` | ❌ W0 | ⬜ pending |
| 03-01-07 | 01 | 1 | REQ-config | — | Trailing-slash normalization works both ways | unit | `python3 -m pytest tests/test_check_config.py::test_trailing_slash_normalization -xq` | ❌ W0 | ⬜ pending |
| 03-01-08 | 01 | 1 | REQ-config | — | `enabled: []` accepted silently, returns empty set | unit | `python3 -m pytest tests/test_check_config.py::test_empty_enabled_list_allowed -xq` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | REQ-filter | T-03-05 | Filtering uses frozenset membership (no code exec) | integration | `python3 -m pytest tests/test_validation_service.py::test_check_config_filtering -xq` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | REQ-filter | — | check_config=None returns all results (backward compat) | integration | `python3 -m pytest tests/test_validation_service.py -xq` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_check_config.py` — 7 unit tests for CheckConfig (does not exist yet; created in Plan 01 Task 1)
- [ ] `check_config.py` — the new module (does not exist yet; created in Plan 01 Task 2)
- [ ] `config/url_checks.yaml` — the production config file (does not exist yet; created in Plan 01 Task 3)

*Note: PyYAML 6.0.1 and Pydantic 2.12.5 already installed — no new framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Results pages produce no false-positive `CTA_MISSING` | REQ-filter | Requires live scraping against staging | Run `python watchdog.py` against a results page URL with `CTA_MISSING` opted out; confirm no false positive in report |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
