---
phase: 03-per-url-test-configuration
reviewed: 2026-04-15T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - constants.py
  - check_config.py
  - config/url_checks.yaml
  - tests/test_check_config.py
  - validation_service.py
  - scraper.py
  - tests/test_validation_service.py
findings:
  critical: 1
  warning: 2
  info: 4
  total: 7
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-04-15T00:00:00Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Phase 3 introduces the `CheckConfig` module (`check_config.py`) that loads a per-URL check matrix from YAML and wires it into the validation pipeline. The core design is sound: `yaml.safe_load()` is used (not `yaml.load()`), the Pydantic v2 `field_validator` is correctly structured (`@classmethod`, right signature, passes value through), backward compatibility via `check_config=None` is intact, and all seven unit tests are well-scoped and meaningful.

One **critical pre-existing bug** was surfaced in `scraper.py` within the Phase 2 authenticated re-QC code path: it passes a `ProgressTracker()` instance (which itself is constructed with missing required arguments) as an extra positional argument to `_run_viewport()` — causing a `TypeError` at runtime whenever any authenticated run triggers a re-QC pass.

Two **warnings** exist in Phase 3 new/changed code: `CheckConfig.load()` does not handle an empty or comment-only YAML file (where `yaml.safe_load()` returns `None`) or malformed YAML (where `yaml.YAMLError` is raised), and `validate_course`'s `check_config` parameter is annotated as `Optional[Any]` instead of `Optional["CheckConfig"]`, silently disabling type-checking for it.

---

## Critical Issues

### CR-01: `_run_viewport()` called with extra argument — `TypeError` in authenticated re-QC path

**File:** `scraper.py:566-573`
**Issue:** The authenticated re-QC block (Phase 2 code, unmodified in Phase 3) contains two compounding bugs that cause a `TypeError` at runtime whenever any authenticated run has issues and triggers a re-QC pass:

1. `ProgressTracker()` is called with no arguments on line 566, but `ProgressTracker.__init__` requires `total: int` and `label: str` — this raises `TypeError: __init__() missing 2 required positional arguments`.
2. Even if construction somehow succeeded, the `recheck_cache` variable is then passed as a 6th positional argument to `self._run_viewport()` (line 569-573), which only accepts 5 positional parameters (`tasks, label, context_kwargs, run_id, pdp_cache`). This raises `TypeError: _run_viewport() takes from 5 to 6 positional arguments but 7 were given`.

The most likely intent was to pass a fresh `PdpCache()` (the correct cache type, which takes no args) for the recheck pass, instead of reusing `auth_cache`. The `recheck_cache` variable and its corresponding `ProgressTracker()` construction should be removed entirely.

```python
# BEFORE (lines 566–573) — crashes at runtime:
recheck_cache = ProgressTracker()          # TypeError: missing 2 required args
with ThreadPoolExecutor(max_workers=2) as rpool:
    rfutures = {
        rpool.submit(
            self._run_viewport, tasks, label,
            auth_desktop_kwargs if label == "desktop" else auth_mobile_kwargs,
            auth_run_id, auth_cache, recheck_cache  # TypeError: 6 args, accepts 5
        ): label
        for label in ("desktop", "mobile")
    }

# AFTER — fresh PdpCache per recheck pass, correct arg count:
with ThreadPoolExecutor(max_workers=2) as rpool:
    rfutures = {
        rpool.submit(
            self._run_viewport, tasks, label,
            auth_desktop_kwargs if label == "desktop" else auth_mobile_kwargs,
            auth_run_id, PdpCache()
        ): label
        for label in ("desktop", "mobile")
    }
```

> **Note:** This bug pre-dates Phase 3; it was introduced during Phase 2. It is surfaced here because `scraper.py` is in-scope as a Phase 3 changed file.

---

## Warnings

### WR-01: `CheckConfig.load()` does not handle null or malformed YAML

**File:** `check_config.py:54-62`
**Issue:** `yaml.safe_load()` returns `None` for any YAML file that is empty or contains only comments (confirmed: `yaml.safe_load("")` → `None`). When `None` is passed to `cls.model_validate(None)`, Pydantic raises an uncaught `ValidationError`, crashing the process at startup instead of falling back to the permissive default. Similarly, a malformed YAML file raises `yaml.YAMLError` which is also not caught — inconsistent with the graceful handling of missing files.

```python
# BEFORE:
try:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return cls.model_validate(data)
except FileNotFoundError:
    logging.warning(
        "Check config %s not found — running all checks for all URLs", path
    )
    return cls(defaults=UrlCheckSpec(enabled=list(KNOWN_CHECK_TYPES)))

# AFTER — also handles empty file and YAML parse errors:
try:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        raise ValueError("Config file is empty or contains only comments")
    return cls.model_validate(data)
except FileNotFoundError:
    logging.warning(
        "Check config %s not found — running all checks for all URLs", path
    )
    return cls(defaults=UrlCheckSpec(enabled=list(KNOWN_CHECK_TYPES)))
except (yaml.YAMLError, ValueError) as exc:
    logging.warning(
        "Check config %s is malformed (%s) — running all checks for all URLs",
        path, exc,
    )
    return cls(defaults=UrlCheckSpec(enabled=list(KNOWN_CHECK_TYPES)))
```

---

### WR-02: `validate_course` `check_config` parameter typed as `Optional[Any]` — erases type safety

**File:** `validation_service.py:43`
**Issue:** `Optional[Any]` is semantically equivalent to `Any` (since `Any | None` is still `Any`), which disables static type-checking for the `check_config` argument entirely. A caller could accidentally pass any object and no type checker would warn. The parameter should be typed as `Optional["CheckConfig"]` — the `TYPE_CHECKING` guard already imports `CheckConfig` from `check_config` specifically for this purpose.

```python
# BEFORE:
def validate_course(
    self,
    course_data: Dict[str, Any],
    check_config: "Optional[Any]" = None,
) -> List[ValidationResult]:

# AFTER — precise type with the already-imported TYPE_CHECKING guard:
def validate_course(
    self,
    course_data: Dict[str, Any],
    check_config: "Optional[CheckConfig]" = None,
) -> List[ValidationResult]:
```

Same fix applies to `validate_all_courses` at line 61:
`check_config: "Optional[Any]" = None` → `check_config: "Optional[CheckConfig]" = None`

---

## Info

### IN-01: Unsubscripted `frozenset` type annotations

**File:** `constants.py:31`, `check_config.py:33`
**Issue:** Both uses of `frozenset` omit the element type. Python 3.9+ supports `frozenset[str]` as a built-in generic, which is more precise and improves IDE/type-checker inference.

```python
# constants.py line 31
KNOWN_CHECK_TYPES: frozenset[str] = frozenset({"CTA_BROKEN", "CTA_MISSING", "PRICE_MISMATCH"})

# check_config.py line 33
def enabled_checks_for(self, url: str) -> frozenset[str]:
```

---

### IN-02: Legacy `typing.Dict` / `typing.List` imports in `check_config.py`

**File:** `check_config.py:9`
**Issue:** `from typing import Dict, List` uses the legacy uppercase aliases deprecated since Python 3.9. The built-in lowercase forms are preferred.

```python
# BEFORE:
from typing import Dict, List

# AFTER (remove the import entirely, use built-ins inline):
# Dict[str, UrlCheckSpec]  →  dict[str, UrlCheckSpec]
# List[str]                →  list[str]
```

---

### IN-03: `enabled_checks_for()` URL normalization does not strip query strings or fragments

**File:** `check_config.py:40-44`
**Issue:** The normalization only calls `url.rstrip("/")`, which handles trailing slashes correctly. However, if a URL passed from the scraper includes a query string (`?ref=plp`) or a fragment (`#section`), it will not match the clean config key. This is a latent edge case rather than an active bug (current scraped URLs appear clean), but worth documenting or guarding against.

```python
# Suggested: use urllib.parse for robust normalization
from urllib.parse import urlparse, urlunparse

def _normalize_url(url: str) -> str:
    """Strip trailing slash; leave scheme, host, and path intact."""
    parsed = urlparse(url.rstrip("/"))
    return urlunparse(parsed._replace(query="", fragment=""))
```

---

### IN-04: `test_load_missing_file` uses a hardcoded `/tmp/` path

**File:** `tests/test_check_config.py:36`
**Issue:** The test hard-codes `/tmp/definitely_not_here_12345.yaml` rather than using pytest's `tmp_path` fixture. While the path is unlikely to exist, using `tmp_path / "nonexistent.yaml"` is the idiomatic pytest approach and avoids any filesystem ambiguity.

```python
# BEFORE:
def test_load_missing_file():
    result = CheckConfig.load("/tmp/definitely_not_here_12345.yaml")

# AFTER:
def test_load_missing_file(tmp_path):
    result = CheckConfig.load(str(tmp_path / "nonexistent.yaml"))
```

---

_Reviewed: 2026-04-15T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
