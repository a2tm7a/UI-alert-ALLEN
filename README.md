# Verification Agent

A modular web scraper and validation system for [allen.in](https://allen.in) that:
- Scrapes course cards across Homepage, PLP, and Olympiad Stream pages
- Verifies each CTA link leads to a valid PDP (Product Detail Page)
- Detects broken links and price mismatches between cards and PDPs
- Generates structured, severity-based validation reports

---

## Quick Start

```bash
# Install dependencies
pip install playwright
playwright install chromium

# Run scraper + validation
python3 scraper.py

# Run validation system demo & tests
python3 test_validators.py
```

Configure which URLs to scrape in `urls.txt`:
```
[HOME]
https://allen.in/

[PLP_PAGES]
https://allen.in/online-coaching-jee

[STREAM_PAGES]
https://allen.in/international-olympiads
```

---

## Architecture

The system uses a layered, modular architecture:

```
scraper.py  (ScraperEngine + Handlers)
    │
    ├── HomepageHandler   — scrapes tab-based course cards
    ├── PLPHandler        — scrapes filter-pill based course listings
    └── StreamHandler     — scrapes class-tab based Olympiad listings
         │
         ▼
    scraped_data.db  (SQLite)
         │
         ▼
validation_service.py  (ValidationService)
         │
    validators/
    ├── base_validator.py          — Abstract base + ValidationResult
    ├── broken_link_validator.py   — Detects broken CTA links
    └── price_mismatch_validator.py — Detects card vs PDP price mismatches
```

### Design Patterns
- **Strategy** — Handler classes per page type (`HomepageHandler`, `PLPHandler`, `StreamHandler`)
- **Chain of Responsibility** — Validators chained: `BrokenLink → PriceMismatch → ...`
- **Template Method** — `BaseValidator._validate()` defines the contract

### ValidationResult Structure
```python
@dataclass
class ValidationResult:
    type: str        # 'BROKEN_LINK' | 'PRICE_MISMATCH'
    severity: str    # 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
    message: str
    course_name: str
    field: str       # which field has the issue (optional)
    expected: Any    # (optional)
    actual: Any      # (optional)
```

### Validation Report Example
```
============================================================
VALIDATION REPORT
============================================================
Total Issues Found: 8

Issues by Type:
  PRICE_MISMATCH: 8

Issues by Severity:
  MEDIUM: 2
  LOW: 6
============================================================
```

---

## Adding a New Validator (3 steps)

**Step 1** — Create `validators/my_validator.py`:
```python
from .base_validator import BaseValidator, ValidationResult

class MyValidator(BaseValidator):
    def _validate(self, course_data):
        issues = []
        # Your logic here
        return issues
```

**Step 2** — Export from `validators/__init__.py`:
```python
from .my_validator import MyValidator
```

**Step 3** — Add to chain in `validation_service.py`:
```python
my_val = MyValidator()
broken_link.set_next(price_mismatch).set_next(my_val)
```

No changes to `scraper.py` or any handler needed. ✅

---

## Backlog

- [x] Course cards CTA should work for Homepage
- [x] Course cards CTA should work for PLP pages
- [x] Course cards CTA should work for Stream pages (Carousel/Tabbed layouts)
- [x] Course card price should match PDP price (automated verification)
- [x] Modular validation system (Phase 1 complete)
- [ ] Alert system — Email/Slack notifications (Phase 2)
- [ ] Sticky banners should be clickable

## Phase 2 Roadmap — Alert System

Goal: route validation reports to Email / Slack in addition to console output.

```
alerters/
├── base_alerter.py     — Abstract base
├── console_alerter.py  — Current log output (default)
├── email_alerter.py    — SMTP email notifications
└── slack_alerter.py    — Slack webhook alerts
```

`AlertService` will sit between `ValidationService` and the alerters, filtering
by severity threshold before dispatching. Configuration via YAML:

```yaml
# config/validation_rules.yaml
alerters:
  - type: email
    severity_threshold: HIGH
    smtp_host: smtp.gmail.com
    recipients: [admin@example.com]
  - type: slack
    severity_threshold: MEDIUM
    webhook_url: https://hooks.slack.com/...
    channel: "#alerts"
```
