Backlog:
[x] Course cards CTA should work for homepage
[x] Course cards CTA should work for PLP pages (Product Listing Pages)
[x] Course cards CTA should work for Stream pages (Carousel/Tabbed layouts)
[x] Course cards price should match of PDPs (PDP verification automated)
[x] Modular validation system (Phase 1 complete)
[] Alert system (Email/Slack) - Phase 2
[] Sticky banners should be clickable

Architecture Note:
The codebase uses a modular Strategy Pattern with:
- **ScraperEngine**: Orchestrates scraping workflow
- **Specialized Handlers**: HomepageHandler, PLPHandler, StreamHandler
- **Validation System**: Modular validators using Chain of Responsibility pattern
  - BrokenLinkValidator: Detects non-functional course links
  - PriceMismatchValidator: Compares card vs PDP prices
  - Easy to add new validators without modifying existing code
- **Future**: Alert system for Email/Slack notifications (see REFACTORING_PLAN.md)

## Quick Start
```bash
# Run scraper with validation
python3 scraper.py

# Test validation system
python3 test_validators.py
```

## Adding New Validators
See `validators/` directory and `test_validators.py` for examples.
