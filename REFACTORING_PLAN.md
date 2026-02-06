# Refactoring Plan for Verification Agent

## Current Architecture Issues

1. **Tight Coupling**: Validation logic (`verify_pdp`) is embedded within scraping handlers
2. **Limited Extensibility**: Adding new validations requires modifying core handler code
3. **No Alert System Foundation**: No infrastructure for notifications
4. **Monolithic Handlers**: Each handler duplicates validation and reporting logic

## Proposed Modular Architecture

### 1. **Separation of Concerns**

```
┌─────────────────────────────────────────────────────────────┐
│                     ScraperEngine                           │
│  - Orchestrates workflow                                    │
│  - Manages browser lifecycle                                │
└─────────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Scrapers   │  │  Validators  │  │   Alerters   │
│  (Handlers)  │  │   (Rules)    │  │ (Notifiers)  │
└──────────────┘  └──────────────┘  └──────────────┘
        │                 │                 │
        └─────────────────┼─────────────────┘
                          ▼
                ┌──────────────────┐
                │  DatabaseManager │
                └──────────────────┘
```

### 2. **Validator Pattern** (Chain of Responsibility)

Create independent validator classes that can be chained:

```python
# validators/base_validator.py
class BaseValidator(ABC):
    def __init__(self):
        self.next_validator = None
    
    def set_next(self, validator):
        self.next_validator = validator
        return validator
    
    @abstractmethod
    def validate(self, course_data):
        """Returns ValidationResult with issues found"""
        pass

# validators/broken_link_validator.py
class BrokenLinkValidator(BaseValidator):
    def validate(self, course_data):
        issues = []
        if course_data['cta_link'] == course_data['base_url']:
            issues.append({
                'type': 'BROKEN_LINK',
                'severity': 'HIGH',
                'message': f"Link doesn't navigate: {course_data['cta_link']}"
            })
        
        if self.next_validator:
            issues.extend(self.next_validator.validate(course_data))
        return issues

# validators/price_mismatch_validator.py
class PriceMismatchValidator(BaseValidator):
    def validate(self, course_data):
        issues = []
        card_price = self.clean_price(course_data.get('price'))
        pdp_price = self.clean_price(course_data.get('pdp_price'))
        
        if card_price and pdp_price and card_price != pdp_price:
            issues.append({
                'type': 'PRICE_MISMATCH',
                'severity': 'MEDIUM',
                'message': f"Price mismatch: {course_data['price']} vs {course_data['pdp_price']}"
            })
        
        if self.next_validator:
            issues.extend(self.next_validator.validate(course_data))
        return issues
```

### 3. **Alert System** (Strategy Pattern)

```python
# alerters/base_alerter.py
class BaseAlerter(ABC):
    @abstractmethod
    def send_alert(self, validation_results):
        pass

# alerters/email_alerter.py
class EmailAlerter(BaseAlerter):
    def __init__(self, smtp_config):
        self.smtp_config = smtp_config
    
    def send_alert(self, validation_results):
        # Send email with validation summary
        pass

# alerters/slack_alerter.py
class SlackAlerter(BaseAlerter):
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
    
    def send_alert(self, validation_results):
        # Post to Slack channel
        pass

# alerters/console_alerter.py
class ConsoleAlerter(BaseAlerter):
    def send_alert(self, validation_results):
        # Current logging behavior
        logging.info("--- VALIDATION REPORT ---")
        for result in validation_results:
            logging.warning(f"{result['severity']}: {result['message']}")
```

### 4. **Configuration-Driven Validation**

```yaml
# config/validation_rules.yaml
validators:
  - name: BrokenLinkValidator
    enabled: true
    severity: HIGH
  
  - name: PriceMismatchValidator
    enabled: true
    severity: MEDIUM
  
  - name: StartDateValidator  # Future validator
    enabled: false
    severity: LOW

alerters:
  - type: console
    enabled: true
  
  - type: email
    enabled: false
    config:
      smtp_host: smtp.gmail.com
      recipients: [admin@example.com]
  
  - type: slack
    enabled: false
    config:
      webhook_url: https://hooks.slack.com/...
```

### 5. **Refactored Flow**

```python
class ScraperEngine:
    def __init__(self, urls_file="urls.txt", config_file="config/validation_rules.yaml"):
        self.urls_file = urls_file
        self.db = DatabaseManager()
        self.handler_map = {...}
        
        # Load validators from config
        self.validator_chain = self._build_validator_chain(config_file)
        
        # Load alerters from config
        self.alerters = self._build_alerters(config_file)
    
    def run(self):
        # 1. Scrape data (existing logic)
        scraped_data = self._scrape_all_urls()
        
        # 2. Validate data (new modular validation)
        validation_results = self._validate_data(scraped_data)
        
        # 3. Send alerts (new alert system)
        self._send_alerts(validation_results)
    
    def _validate_data(self, scraped_data):
        all_issues = []
        for course in scraped_data:
            issues = self.validator_chain.validate(course)
            if issues:
                all_issues.extend(issues)
                # Update database with flags
                self.db.update_validation_flags(course['id'], issues)
        return all_issues
    
    def _send_alerts(self, validation_results):
        for alerter in self.alerters:
            alerter.send_alert(validation_results)
```

## Migration Strategy

### Phase 1: Extract Validators (Week 1)
- [ ] Create `validators/` directory
- [ ] Implement `BaseValidator` abstract class
- [ ] Extract `BrokenLinkValidator` from `verify_pdp()`
- [ ] Extract `PriceMismatchValidator` from `verify_pdp()`
- [ ] Update handlers to use validator chain
- [ ] **No breaking changes** - maintain backward compatibility

### Phase 2: Implement Alert System (Week 2)
- [ ] Create `alerters/` directory
- [ ] Implement `BaseAlerter` abstract class
- [ ] Implement `ConsoleAlerter` (migrate current logging)
- [ ] Implement `EmailAlerter` stub
- [ ] Implement `SlackAlerter` stub
- [ ] Update `ScraperEngine` to use alerters

### Phase 3: Configuration System (Week 3)
- [ ] Create `config/` directory
- [ ] Implement YAML config loader
- [ ] Make validators configurable
- [ ] Make alerters configurable
- [ ] Add validation severity levels

### Phase 4: Enhanced Database Schema (Week 4)
- [ ] Add `validation_issues` table for detailed issue tracking
- [ ] Migrate from binary flags to structured issue records
- [ ] Add validation run history
- [ ] Add alert delivery tracking

## Benefits

1. **Easy to Add New Validators**: Just create a new class implementing `BaseValidator`
2. **Easy to Add New Alerters**: Just create a new class implementing `BaseAlerter`
3. **Configuration-Driven**: Enable/disable features without code changes
4. **Testable**: Each validator and alerter can be unit tested independently
5. **Maintainable**: Clear separation of concerns
6. **Scalable**: Can add complex validation rules without touching scraping logic

## File Structure After Refactoring

```
Verification-Agent/
├── scraper.py                    # Main orchestration
├── config/
│   └── validation_rules.yaml     # Configuration
├── scrapers/
│   ├── base_handler.py           # BasePageHandler
│   ├── homepage_handler.py       # HomepageHandler
│   ├── plp_handler.py            # PLPHandler
│   └── stream_handler.py         # StreamHandler
├── validators/
│   ├── base_validator.py         # Abstract base
│   ├── broken_link_validator.py
│   ├── price_mismatch_validator.py
│   └── start_date_validator.py   # Future
├── alerters/
│   ├── base_alerter.py           # Abstract base
│   ├── console_alerter.py
│   ├── email_alerter.py
│   └── slack_alerter.py
├── database/
│   └── db_manager.py             # DatabaseManager
└── utils/
    └── helpers.py                # Shared utilities
```
