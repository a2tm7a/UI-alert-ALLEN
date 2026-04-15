# Phase 3: Per-URL Test Configuration File — Research

**Researched:** 2026-04-15  
**Domain:** Python configuration management, validation filtering, YAML schema design  
**Confidence:** HIGH

---

## Summary

Phase 3 introduces a configuration file that acts as a check matrix: URLs are rows, validation check types are columns, and each cell is an opt-in/out boolean. The goal is to let operators control which checks run on which pages without touching Python code.

The key insight from codebase inspection is that **validation runs post-scrape** against the SQLite `courses` table. Each `course_data` dict already carries `base_url` from the DB row. This means per-URL check filtering can be applied inside `ValidationService.validate_course()` — filter `ValidationResult` objects by `result.type` before returning them. No changes to scrapers, handlers, or individual validators are required.

The environment already has PyYAML 6.0.1 and Pydantic 2.12.5 installed. Zero new dependencies are needed. YAML is the correct format — it supports comments (unlike JSON), is human-editable, and the README already shows a planned `config/watchdog.yaml` YAML alerter config, establishing `config/` as the right home for WatchDog config files.

**Primary recommendation:** Create `config/url_checks.yaml` with a `defaults` block and a per-URL `urls` block. Load it into a `CheckConfig` class (Pydantic model). Pass `CheckConfig` to `ValidationService`; filter `ValidationResult` objects by `result.type` per `base_url`. URLs absent from config fall back to defaults (all current checks enabled).

---

## Codebase Findings

### Current Validation Flow [VERIFIED: codebase]

```
ScraperEngine.run()
  └─ ValidationService.validate_all_courses(run_id)
       └─ for each course row in DB:
            course_data = dict(row)   # includes base_url, viewport, etc.
            results = validator_chain.validate(course_data)
```

The `course_data` dict passed to `validate_course()` already contains `base_url` [VERIFIED: `validation_service.py` line 67–73]. This is the hook point for per-URL filtering — no schema changes, no new DB columns.

### Existing Check Types [VERIFIED: codebase]

| Check Type (`result.type`) | Produced by | Severity | Status |
|---|---|---|---|
| `CTA_BROKEN` | `PurchaseCTAValidator` | CRITICAL | Shipped |
| `CTA_MISSING` | `PurchaseCTAValidator` | HIGH | Shipped |
| `PRICE_MISMATCH` | `PriceMismatchValidator` | MEDIUM | Shipped |
| `STICKY_MISMATCH` | — (not yet built) | HIGH | Pending (PRD R-04, R-05) |
| `TAB_MISMATCH` | — (not yet built) | MEDIUM | Pending (PRD R-06) |
| `DATE_MISSING` | — (not yet built) | LOW | Pending (PRD R-07) |

**Important:** `CTA_BROKEN` and `CTA_MISSING` are produced by the **same validator** (`PurchaseCTAValidator`). They cannot be split at the validator-chain level without restructuring the validator. Filtering at the `ValidationResult.type` level (post-validate) handles both cleanly. [VERIFIED: `validators/purchase_cta_validator.py`]

### Existing URL Sections in `urls.txt` [VERIFIED: `urls.txt`]

| Section tag | Example URLs | Sensible defaults |
|---|---|---|
| `HOME` | `allen.in/` | All 3 checks |
| `PLP_PAGES` | `allen.in/jee/online-coaching-class-11` | All 3 checks |
| `STREAM_PAGES` | `allen.in/jee`, `allen.in/international-olympiads/class-8` | All 3 checks |
| `RESULTS_PAGES` | `allen.in/jee/results-2025`, `allen.in/neet/result-2025` | `CTA_BROKEN` only — results pages display past-result cards, not purchase CTAs or current prices |

Results pages are the primary real-world case for disabling checks: they surface alumni result cards where `price_mismatch` and `cta_missing` would likely produce false positives.

### Validator Chain Construction [VERIFIED: `validation_service.py` lines 23–35]

```python
def _build_default_validator_chain(self) -> BaseValidator:
    cta = PurchaseCTAValidator()
    price_mismatch = PriceMismatchValidator()
    cta.set_next(price_mismatch)
    return cta
```

This is currently a static, hardcoded chain. Phase 3 makes it config-driven without changing the validators themselves.

### Available Libraries [VERIFIED: local Python env]

| Library | Version | Role |
|---|---|---|
| PyYAML | 6.0.1 | YAML loading |
| Pydantic | 2.12.5 | Config schema validation |
| tomllib | built-in (Python 3.11+) | TOML parsing (alternative, no install needed) |

No new dependencies required. [VERIFIED: `python3 -c "import yaml; print(yaml.__version__)"` → `6.0.1`; `python3 -c "import pydantic; print(pydantic.__version__)"` → `2.12.5`]

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---|---|---|---|
| PyYAML | 6.0.1 (installed) | Parse `url_checks.yaml` | Already in env; `yaml.safe_load()` is the standard |
| Pydantic v2 | 2.12.5 (installed) | Validate config schema, type-check fields | Already in env; fails fast with clear error messages |

### No New Installations Required

```bash
# Nothing to install — PyYAML and Pydantic are already available
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|---|---|---|
| YAML | TOML | TOML is built-in (Python 3.11+), but TOML URLs as dict keys require quoting (`["https://allen.in/..."]`) — awkward for a URL matrix |
| YAML | JSON | JSON lacks comments — operators can't annotate why a URL has non-default checks |
| Pydantic validation | Manual dict parsing | Pydantic gives free type coercion, error messages with field names, and IDE autocomplete on the model |

---

## Architecture Patterns

### Recommended Project Structure

```
config/
├── url_checks.yaml        # new — the per-URL check matrix
└── watchdog.yaml          # planned for Phase 3 alerter config (from README)
check_config.py            # new — CheckConfig class (Pydantic model + loader)
validation_service.py      # modified — accept CheckConfig, filter results per URL
```

### Pattern 1: Post-Validate Result Filtering

**What:** Run the full validator chain for every course record. After getting raw `ValidationResult` objects, drop any whose `result.type` is not in the enabled-checks set for that URL.

**When to use:** Correct for WatchDog because validators are stateful chain links — splitting or conditionally skipping them mid-chain risks breaking the Chain-of-Responsibility pattern. Filtering outputs is non-invasive.

**Why not pre-filter the validator chain?** `CTA_BROKEN` and `CTA_MISSING` are produced by the same validator instance. If a URL wants `CTA_BROKEN` but not `CTA_MISSING`, you cannot remove the validator — only filter its output.

```python
# check_config.py
from pydantic import BaseModel, field_validator
from typing import List, Dict
import yaml
import logging

KNOWN_CHECKS = {"CTA_BROKEN", "CTA_MISSING", "PRICE_MISMATCH"}

class UrlCheckSpec(BaseModel):
    enabled: List[str]

    @field_validator("enabled")
    @classmethod
    def validate_check_names(cls, v):
        unknown = set(v) - KNOWN_CHECKS
        if unknown:
            logging.warning(f"Unknown check names in config: {unknown} — ignored")
        return v

class CheckConfig(BaseModel):
    version: int = 1
    defaults: UrlCheckSpec
    urls: Dict[str, UrlCheckSpec] = {}

    def enabled_checks_for(self, url: str) -> set:
        """Return the set of enabled check types for a given URL."""
        if url in self.urls:
            return set(self.urls[url].enabled)
        return set(self.defaults.enabled)

    @classmethod
    def load(cls, path: str = "config/url_checks.yaml") -> "CheckConfig":
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            return cls.model_validate(data)
        except FileNotFoundError:
            logging.warning(f"Check config {path} not found — using all checks for all URLs")
            return cls(defaults=UrlCheckSpec(enabled=list(KNOWN_CHECKS)))
```

```python
# validation_service.py — modified validate_course()
def validate_course(
    self,
    course_data: dict,
    check_config: CheckConfig | None = None,
) -> list[ValidationResult]:
    raw = self.validator_chain.validate(course_data)
    if check_config is None:
        return raw
    base_url = course_data.get("base_url", "")
    enabled = check_config.enabled_checks_for(base_url)
    return [r for r in raw if r.type in enabled]
```

### Pattern 2: Graceful Degradation on Missing Config

**What:** If `config/url_checks.yaml` does not exist, `CheckConfig.load()` catches `FileNotFoundError` and returns a default config with all current checks enabled for all URLs. The system behaves exactly as it does today.

**When to use:** Always. The config file is optional — existing deployments without it continue to work unchanged.

### Anti-Patterns to Avoid

- **YAML anchors for URL groups:** Tempting to use `&plp_defaults` YAML anchors to share check lists across URL groups. Avoid — it adds YAML complexity that confuses non-developers editing the file. Use `defaults` + explicit per-URL overrides instead.
- **Storing check configs inside `urls.txt`:** The current `urls.txt` format is simple and working. Don't extend it with check annotations (e.g., `https://allen.in/neet/result-2025 [cta_broken]`). Separate concerns: `urls.txt` → what to scrape; `url_checks.yaml` → what to validate.
- **Validator-level conditional logic:** Don't add `if url in disabled_urls: return []` inside `PurchaseCTAValidator._validate()`. Validators must remain URL-agnostic; filtering is the config layer's responsibility.

---

## Config File Design

### Canonical `config/url_checks.yaml` Format

```yaml
version: 1

# Checks enabled for any URL not listed in the urls section below.
# To disable a check globally, remove it from this list.
defaults:
  enabled:
    - CTA_BROKEN
    - CTA_MISSING
    - PRICE_MISMATCH

# Per-URL overrides — fully replaces defaults for that URL.
# Use this when a page type doesn't support a particular check.
urls:
  # Results pages: display alumni result cards, not purchasable course cards.
  # Price mismatch and missing CTA checks would produce false positives.
  https://allen.in/neet/result-2025:
    enabled: [CTA_BROKEN]
  https://allen.in/neet/results-2024:
    enabled: [CTA_BROKEN]
  https://allen.in/neet/results-2023:
    enabled: [CTA_BROKEN]
  https://allen.in/neet/results-2022:
    enabled: [CTA_BROKEN]
  https://allen.in/jee/results-2026:
    enabled: [CTA_BROKEN]
  https://allen.in/jee/results-2025:
    enabled: [CTA_BROKEN]
  https://allen.in/jee/results-2024:
    enabled: [CTA_BROKEN]
  https://allen.in/jee/results-2023:
    enabled: [CTA_BROKEN]
  https://allen.in/jee/results-2022:
    enabled: [CTA_BROKEN]
  https://allen.in/classes-6-10/results:
    enabled: [CTA_BROKEN]

  # Registration page: no course cards with prices.
  https://allen.in/aiot-register:
    enabled: [CTA_BROKEN]
```

### Check Name Registry

Check names in `url_checks.yaml` are the **exact strings** used in `ValidationResult.type`. The `CheckConfig.enabled_checks_for()` method compares them directly via set membership. Names must match exactly (case-sensitive).

Current valid names: `CTA_BROKEN`, `CTA_MISSING`, `PRICE_MISMATCH`

When new validators are added (e.g., `STICKY_MISMATCH` in a future phase), they are automatically supported in `url_checks.yaml` — just add the name to `defaults.enabled` and any per-URL overrides. No code changes to `CheckConfig` are needed unless the name requires whitelisting in the Pydantic validator.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| YAML parsing | Custom line-by-line parser | `yaml.safe_load()` from PyYAML | Handles multi-line, anchors, comments; already installed |
| Config schema validation | Manual `isinstance()` checks | Pydantic `BaseModel` | Free field-level error messages, type coercion, IDE autocomplete |
| Unknown check name errors | Silent ignore | Pydantic `@field_validator` with `logging.warning()` | Warns loudly at startup if a check name is misspelled |

**Key insight:** YAML + Pydantic gives operator-facing error messages ("field `enabled` must be a list") without writing any custom validation code.

---

## Common Pitfalls

### Pitfall 1: URL Trailing-Slash Mismatch
**What goes wrong:** `url_checks.yaml` has `https://allen.in/` but the DB `base_url` is `https://allen.in` (no trailing slash), or vice versa. The config lookup fails silently and the URL falls back to defaults.  
**Why it happens:** HTTP redirects and the scraper's `page.goto()` may normalize URLs differently.  
**How to avoid:** Normalize both the config key and the lookup URL in `enabled_checks_for()` — strip trailing slashes from both sides before comparison.  
**Warning signs:** A URL you configured with `enabled: []` still produces check results.

```python
def enabled_checks_for(self, url: str) -> set:
    normalized = url.rstrip("/")
    for config_url, spec in self.urls.items():
        if config_url.rstrip("/") == normalized:
            return set(spec.enabled)
    return set(self.defaults.enabled)
```

### Pitfall 2: Unknown Check Name Silently Allowed
**What goes wrong:** Operator writes `CTA_BROKN` (typo) in `url_checks.yaml`. The filter never matches any results (no `ValidationResult` has type `CTA_BROKN`), effectively disabling the check without any warning.  
**Why it happens:** Python set membership check passes; typo is not caught.  
**How to avoid:** Add a Pydantic `@field_validator` on `enabled` that logs a warning for names not in `KNOWN_CHECKS`. Don't hard-fail (to future-proof for new check types being added before the registry is updated).  
**Warning signs:** An expected issue doesn't appear in the report for a URL.

### Pitfall 3: Config File Not Found Breaks the Run
**What goes wrong:** `CheckConfig.load()` raises `FileNotFoundError` and the entire run fails on the first validation call.  
**Why it happens:** Config file is missing on a new deployment or renamed.  
**How to avoid:** `load()` catches `FileNotFoundError` and returns a permissive default config (all checks enabled). Log a WARNING so the operator knows the config was not found.

### Pitfall 4: Mutable `KNOWN_CHECKS` Creates Split Brain
**What goes wrong:** A new validator produces `STICKY_MISMATCH` results, but `KNOWN_CHECKS` in `check_config.py` is not updated. The validator fires, but `STICKY_MISMATCH` is always logged as "unknown" and never filterable per URL.  
**Why it happens:** `KNOWN_CHECKS` is a maintenance point — it must stay in sync with real validator outputs.  
**How to avoid:** Either (a) remove the whitelist validator and only warn on unknown names, or (b) auto-populate `KNOWN_CHECKS` from `constants.py` if check type names are centralized there. Option (b) is better for WatchDog since `constants.py` already exists for shared strings.

---

## Integration Points

### `ValidationService` Changes (minimal)

```python
# Current signature
def validate_all_courses(self, run_id=None) -> List[ValidationResult]:

# Phase 3 signature — CheckConfig is optional for backward compat
def validate_all_courses(
    self,
    run_id: Optional[int] = None,
    check_config: Optional[CheckConfig] = None,
) -> List[ValidationResult]:
    ...
    for row in cursor.fetchall():
        course_data = dict(row)
        issues = self.validate_course(course_data, check_config=check_config)
        ...
```

### `ScraperEngine.run()` Changes (minimal)

```python
# In ScraperEngine.__init__ or run():
from check_config import CheckConfig
check_config = CheckConfig.load("config/url_checks.yaml")

# Pass to ValidationService
vs = ValidationService(self.db.db_name)
issues = vs.validate_all_courses(run_id, check_config=check_config)
```

### Test Impact

Existing tests in `tests/test_validation_service.py` use `ValidationService` without `check_config` — they continue to work unchanged (default `None` = run all checks). New tests exercise the filtering path.

---

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest (already installed) |
| Config file | `pytest.ini` (exists in root) |
| Quick run command | `python3 -m pytest tests/test_check_config.py -x` |
| Full suite command | `python3 -m pytest` |

### Phase Requirements → Test Map

| Behavior | Test Type | Automated Command |
|---|---|---|
| `CheckConfig.load()` reads valid YAML | unit | `pytest tests/test_check_config.py::test_load_valid_config -x` |
| `CheckConfig.load()` returns defaults when file missing | unit | `pytest tests/test_check_config.py::test_load_missing_file -x` |
| `enabled_checks_for()` returns URL-specific checks | unit | `pytest tests/test_check_config.py::test_url_override -x` |
| `enabled_checks_for()` falls back to defaults for unconfigured URL | unit | `pytest tests/test_check_config.py::test_url_fallback_to_defaults -x` |
| Trailing-slash normalization in URL matching | unit | `pytest tests/test_check_config.py::test_trailing_slash_normalization -x` |
| `ValidationService` filters results by enabled checks | unit | `pytest tests/test_validation_service.py::test_check_config_filtering -x` |
| Unknown check name in YAML logs warning (not crash) | unit | `pytest tests/test_check_config.py::test_unknown_check_name_warns -x` |
| Integration: `url_checks.yaml` → filtered validation results | integration | `python3 -m pytest tests/ -x` |

### Wave 0 Gaps

- [ ] `tests/test_check_config.py` — new test file for `CheckConfig` class (does not exist yet)
- [ ] `config/url_checks.yaml` — the config file itself (does not exist yet)
- [ ] `check_config.py` — the new module (does not exist yet)

---

## Environment Availability

Step 2.6: All dependencies are pre-installed. No external tools, services, or CLIs beyond the project's Python environment are required.

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| PyYAML | `yaml.safe_load()` in `check_config.py` | ✓ | 6.0.1 | — |
| Pydantic v2 | `CheckConfig` schema validation | ✓ | 2.12.5 | — |
| pytest | Test suite | ✓ | (see `requirements.txt`) | — |

---

## Security Domain

This phase introduces a YAML config file read at runtime. No secrets are stored in it (it contains only URL strings and check names). Security considerations are minimal:

| Risk | Mitigation |
|---|---|
| YAML `yaml.load()` with `Loader=None` allows arbitrary Python execution | Use `yaml.safe_load()` exclusively — already the standard recommendation |
| Config file committed with sensitive URL patterns | URL paths are not sensitive; no credentials involved |
| Path traversal in `CheckConfig.load(path)` | Path is hardcoded (`config/url_checks.yaml`) in `ScraperEngine`; not user-supplied |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | Results pages (`RESULTS_PAGES` section) contain alumni result cards that would produce false positives for `CTA_MISSING` and `PRICE_MISMATCH` | Codebase Findings / Config File Design | Low — operator can reconfigure via YAML; no code impact |
| A2 | `allen.in/aiot-register` has no purchasable course cards | Config File Design | Low — same mitigation as A1 |
| A3 | URL normalization (trailing-slash stripping) is sufficient to handle all URL variants in the DB | Pitfall 1 | Medium — if the DB stores query strings or fragments, further normalization may be needed |

---

## Open Questions

1. **Should the config support section-level defaults (e.g., all `RESULTS_PAGES` get `CTA_BROKEN` only)?**
   - What we know: Results pages are the primary use case for non-default checks; there are 10 of them in `urls.txt`
   - What's unclear: Whether section-level keys (matching `urls.txt` section tags) would be more ergonomic than listing 10 URLs individually
   - Recommendation: Start with per-URL keys (simpler, more explicit). A `sections:` block can be added later if the URL list grows large. The 10-URL list is manageable and explicit.

2. **Should `enabled: []` (empty list) be valid — disabling all checks for a URL?**
   - What we know: `aiot-register` is a registration page with no course cards
   - What's unclear: Whether completely skipping validation for a URL is intentional or an accidental misconfiguration
   - Recommendation: Allow `enabled: []` but log an INFO message: "All checks disabled for URL X — skipping validation". This documents intent without blocking the run.

3. **Should the config be hot-reloaded between runs or read once at startup?**
   - What we know: WatchDog runs as a single-process nightly job (not a daemon)
   - Recommendation: Read once at `ScraperEngine.__init__()` or at the start of `run()`. No hot-reload needed.

---

## Sources

### Primary (HIGH confidence)
- Codebase: `validation_service.py`, `validators/base_validator.py`, `validators/purchase_cta_validator.py`, `urls.txt`, `constants.py`, `scraper.py` — all verified by direct inspection
- Local Python environment: `python3 -c "import yaml; print(yaml.__version__)"` → 6.0.1; `python3 -c "import pydantic; print(pydantic.__version__)"` → 2.12.5

### Secondary (MEDIUM confidence)
- PyYAML official docs: `yaml.safe_load()` is the safe, standard way to parse YAML in Python [ASSUMED from training knowledge — well-established, stable API unchanged for years]
- Pydantic v2 `BaseModel` + `@field_validator`: standard schema validation pattern [ASSUMED — verified indirectly by confirming Pydantic 2.12.5 is installed]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — PyYAML and Pydantic already installed and verified
- Architecture: HIGH — integration points verified directly in the codebase
- Config file design: HIGH — based on real `urls.txt` content and existing validator output types
- Pitfalls: HIGH — derived from concrete codebase facts (same validator produces CTA_BROKEN and CTA_MISSING; URL normalization is a known YAML key lookup issue)

**Research date:** 2026-04-15  
**Valid until:** 2026-07-15 (stable ecosystem; no time-sensitive dependencies)
