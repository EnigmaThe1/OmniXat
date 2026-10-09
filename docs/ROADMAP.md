# Personal-first delivery plan

## Milestone 0.1 — In progress
- [x] Repository initialised on a development branch
- [x] FastAPI and Next.js foundation
- [x] Postgres Compose with health checks
- [x] Single-owner access and basic audit events
- [x] Manual/verified company records with official due dates when available
- [x] Personal Self Assessment year toggle and CT-period standard deadlines
- [x] Calendar with provenance and uncertainty labels
- [ ] Validate Docker builds and startup on the target Ubuntu machine
- [ ] Replace create_all with repeatable migrations
- [ ] Perform additional security assessment

## 0.2 — Financial evidence
- Hardened storage and backups.
- Owner-controlled local bank CSV import with deduplication and reconciliation.
- Receipt/invoice uploads with original hashes and document provenance.
- Separate individual, sole-trader and corporate ledgers.

## 0.3 — Guided questions
- Deterministic missing-fact rules followed by optional local Ollama / cloud model.
- Question inbox with evidence, confidence, period and user validation.
- Never turn an LLM suggestion into an accepted accounting entry automatically.

## 0.4 — Tax draft engine
- Versioned UK-year tax rules and independent worked examples.
- Draft accounts and Self Assessment/CT600 calculations for narrowly defined cases.
- Deterministic calculation and accountant review gates.

## 0.5 — Submission sandbox
- HMRC / Companies House API permission matrix and eligibility testing.
- Sandbox validation, approved declarations, no unsupported impersonation.
- Separate submitted / acknowledged / accepted state, with safe retries.

## 1.0 — Personal pilot
- Tested production credentials for supported types, if granted.
- Shadow run against independently checked real tax returns.
- Reliable restore, secure storage, reporting and reminders.

## Deferred
Public SaaS accounts, marketing website, subscriptions, accountant marketplace, international expansion, automated tax payments.
