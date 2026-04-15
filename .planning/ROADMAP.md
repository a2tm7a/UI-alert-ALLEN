# WatchDog — Roadmap

## Active Phases

### Phase 2: Authenticated Validation

**Status:** Complete (2026-04-15) — 5/5 plans

### Phase 3: Per-URL Test Configuration File

**Goal:** A configuration file defining which checks to run on which URLs — structured as a matrix where URLs are rows and checks are columns. Each URL can opt in/out of specific checks (e.g., URL A runs checks A, B, C, D; URL B runs checks A, B, E, F).
**Requirements:** REQ-config, REQ-filter
**Depends on:** Phase 2
**Plans:** 2 plans

Plans:
- [ ] 03-01-PLAN.md — CheckConfig Pydantic module, config/url_checks.yaml, and unit test scaffold
- [ ] 03-02-PLAN.md — Wire CheckConfig into ValidationService and ScraperEngine

---

## Backlog

(empty)
