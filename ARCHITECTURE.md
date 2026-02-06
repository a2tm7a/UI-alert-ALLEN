# Architecture Overview

## Before Phase 1 (Monolithic)

```
┌─────────────────────────────────────────────────────────┐
│                    scraper.py                           │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │ ScraperEngine                                    │  │
│  │  - Scraping logic                                │  │
│  │  - Validation logic (inline)                     │  │
│  │  - Reporting logic (inline)                      │  │
│  │  - All tightly coupled                           │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Handlers (Homepage, PLP, Stream)                 │  │
│  │  - Scraping                                      │  │
│  │  - verify_pdp() with validation mixed in        │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

Problems:
❌ Hard to add new validation rules
❌ Validation logic scattered across files
❌ No structured issue reporting
❌ Difficult to test validation independently
```

---

## After Phase 1 (Modular)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         scraper.py                                  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ ScraperEngine                                                │  │
│  │  - Orchestrates workflow                                     │  │
│  │  - Delegates to handlers for scraping                        │  │
│  │  - Delegates to ValidationService for validation             │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Handlers (Homepage, PLP, Stream)                             │  │
│  │  - ONLY scraping logic                                       │  │
│  │  - Extract data and save to DB                               │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Uses
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    validation_service.py                            │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ ValidationService                                            │  │
│  │  - Builds validator chain                                    │  │
│  │  - Validates all courses                                     │  │
│  │  - Generates summaries                                       │  │
│  │  - Formats reports                                           │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ Uses
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         validators/                                 │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │ BaseValidator (Abstract)                                   │    │
│  │  - Defines validation interface                            │    │
│  │  - Implements chain mechanism                              │    │
│  │  - Returns ValidationResult objects                        │    │
│  └────────────────────────────────────────────────────────────┘    │
│                           │                                         │
│          ┌────────────────┼────────────────┐                        │
│          ▼                ▼                ▼                        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐               │
│  │   Broken     │ │    Price     │ │   Future     │               │
│  │    Link      │ │   Mismatch   │ │  Validators  │               │
│  │  Validator   │ │  Validator   │ │  (Easy to    │               │
│  │              │ │              │ │   add!)      │               │
│  └──────────────┘ └──────────────┘ └──────────────┘               │
└─────────────────────────────────────────────────────────────────────┘

Benefits:
✅ Easy to add new validators (just create a new class)
✅ Validation logic centralized and organized
✅ Structured ValidationResult objects
✅ Each component independently testable
✅ Clear separation of concerns
```

---

## Data Flow

```
1. SCRAPING PHASE
   ┌──────────┐
   │  URLs    │
   │ (urls.txt)│
   └────┬─────┘
        │
        ▼
   ┌──────────────────┐
   │ ScraperEngine    │
   │ - Launches browser│
   │ - Dispatches URLs│
   └────┬─────────────┘
        │
        ▼
   ┌──────────────────────────────────┐
   │ Handlers (Homepage/PLP/Stream)   │
   │ - Navigate to pages              │
   │ - Extract course data            │
   │ - Visit PDPs for verification    │
   └────┬─────────────────────────────┘
        │
        ▼
   ┌──────────────────┐
   │   Database       │
   │ (scraped_data.db)│
   │ - Stores courses │
   │ - Stores flags   │
   └────┬─────────────┘
        │
        │
2. VALIDATION PHASE
        │
        ▼
   ┌──────────────────────┐
   │ ValidationService    │
   │ - Reads all courses  │
   │ - Builds validator   │
   │   chain              │
   └────┬─────────────────┘
        │
        ▼
   ┌─────────────────────────────────┐
   │ Validator Chain                 │
   │ BrokenLink → PriceMismatch → ...│
   │ - Each validates course data    │
   │ - Returns ValidationResult[]    │
   └────┬────────────────────────────┘
        │
        ▼
   ┌──────────────────────┐
   │ Validation Report    │
   │ - Summary by type    │
   │ - Summary by severity│
   │ - Detailed issues    │
   └──────────────────────┘
        │
        │
3. ALERT PHASE (Phase 2 - Future)
        │
        ▼
   ┌──────────────────────┐
   │ Alert System         │
   │ - Email              │
   │ - Slack              │
   │ - Console (current)  │
   └──────────────────────┘
```

---

## Validator Chain Pattern

```
Course Data
     │
     ▼
┌─────────────────────┐
│ BrokenLinkValidator │
│ - Check if link     │
│   navigates         │
└──────┬──────────────┘
       │ next_validator
       ▼
┌─────────────────────┐
│PriceMismatchValidator│
│ - Compare card vs   │
│   PDP prices        │
└──────┬──────────────┘
       │ next_validator
       ▼
┌─────────────────────┐
│ StartDateValidator  │ ← Future validator
│ - Compare dates     │   (easy to add!)
└──────┬──────────────┘
       │
       ▼
  ValidationResult[]
  (All issues found)
```

---

## ValidationResult Structure

```python
@dataclass
class ValidationResult:
    type: str          # 'BROKEN_LINK', 'PRICE_MISMATCH'
    severity: str      # 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    message: str       # Human-readable description
    course_name: str   # Which course has the issue
    field: str         # Which field (optional)
    expected: Any      # What was expected (optional)
    actual: Any        # What was found (optional)
```

**Example:**
```python
ValidationResult(
    type='PRICE_MISMATCH',
    severity='MEDIUM',
    message='Price on card doesn\'t match price on PDP',
    course_name='JEE Nurture Course',
    field='price',
    expected='₹ 10,000',
    actual='₹ 15,000'
)
```

---

## Adding a New Validator (3 Steps)

```
Step 1: Create validators/my_validator.py
┌─────────────────────────────────────────┐
│ from .base_validator import            │
│     BaseValidator, ValidationResult     │
│                                         │
│ class MyValidator(BaseValidator):      │
│     def _validate(self, course_data):  │
│         issues = []                     │
│         # Your validation logic         │
│         return issues                   │
└─────────────────────────────────────────┘

Step 2: Update validators/__init__.py
┌─────────────────────────────────────────┐
│ from .my_validator import MyValidator   │
└─────────────────────────────────────────┘

Step 3: Update validation_service.py
┌─────────────────────────────────────────┐
│ my_val = MyValidator()                  │
│ broken.set_next(price).set_next(my_val) │
└─────────────────────────────────────────┘

Done! ✅ No changes to scraper.py needed
```

---

## Phase 2 Preview: Alert System

```
┌──────────────────────────────────────────┐
│      ValidationService                   │
│      - Collects ValidationResults        │
└──────────┬───────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────┐
│      AlertService                        │
│      - Filters by severity               │
│      - Formats messages                  │
└──────────┬───────────────────────────────┘
           │
     ┌─────┼─────┐
     ▼     ▼     ▼
┌────────┐ ┌────────┐ ┌────────┐
│Console │ │ Email  │ │ Slack  │
│Alerter │ │Alerter │ │Alerter │
└────────┘ └────────┘ └────────┘
```

**Coming in Phase 2!**
