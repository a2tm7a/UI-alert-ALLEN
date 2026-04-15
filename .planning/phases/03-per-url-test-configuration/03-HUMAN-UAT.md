---
status: partial
phase: 03-per-url-test-configuration
source: [03-VERIFICATION.md]
started: 2026-04-15T00:00:00Z
updated: 2026-04-15T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Live scrape — results page produces no false-positive CTA_MISSING or PRICE_MISMATCH
expected: When running a live scraping pass against a results page URL (e.g. https://allen.in/jee/results-2025), the validation report should contain NO CTA_MISSING and NO PRICE_MISMATCH issues for that URL. Only CTA_BROKEN checks should be evaluated (and may or may not fire depending on page state).
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
