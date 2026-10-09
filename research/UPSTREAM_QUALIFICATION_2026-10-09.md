# OmniXat upstream qualification — 9 October 2026

**Status: static source audit. No upstream binaries tested or HMRC filings made.** Full local research report is available separately; this document captures the actionable decision and gates for the public repository.

## Decisions

| Component | Candidate | Review decision | Remaining gate |
|---|---|---|---|
| CT600 XML / iXBRL renderer | [benhuckvale/ct600-filing](https://github.com/benhuckvale/ct600-filing) — MIT | **Priority sandbox spike**, not approved for live integration | Run pinned offline unit tests, synthetic filing examples, official LTS and separately authorised Test-in-Live |
| Secondary CT600 implementation | [cybermaggedon/ct600](https://github.com/cybermaggedon/ct600) — GPL-3.0 | Compare outputs / research; licence review before embedding | Accounting coverage, current taxonomies |
| Independent iXBRL validation | [Arelle](https://github.com/Arelle/Arelle) — Apache-2.0 | **Preferred validation candidate** | Version/digest pin, UK taxonomy, good/bad fixtures, official filing-gateway check |
| Double-entry ledger | [GnuCash](https://github.com/Gnucash/gnucash) | Test source/import/export; **not yet chosen as canonical ledger** | Single-writer semantics, audit, reversal, bank recon, multi-entity isolation |
| Documents / extraction | [Bookcomet](https://github.com/RRCTL/Bookcomet-a) — Apache-2.0 | Isolated local-model extraction trial | Accuracy on synthetic test set, data residency, review-only posting |
| MTD Self Assessment | [ac000/itsa](https://github.com/ac000/itsa) — GPL-2.0 | Reference only; build current versioned HMRC API adapter | API version, developer permission, sandbox verification |
| Agent-ledger architecture | [ERPClaw](https://github.com/avansaber/erpclaw) — GPL-3.0 | Study design; no wholesale fork | UK compliance, scope, future licensing |

Revisions pinned in [upstreams.lock.json](upstreams.lock.json); **none** are runtime-qualified.

## CT600 code review: concrete integration blockers

Source reviewed at `benhuckvale/ct600-filing` pinned commit:
- `ct600/cli.py` permits `--live` after a CLI confirmation; OmniXat must provide a separate backend-authorised declaration/approval gate.
- `ct600/submit.py` persists raw request/response XML, potentially including credentials, private identifiers and tax figures. A production adapter must use encrypted, access-controlled storage; never write raw submissions to public repo or ordinary logs.
- `ct600/submit.py` sends polling requests to a response-provided endpoint. Restrict to allowlisted, TLS-protected official hosts; do not follow unexpected redirects.
- Asynchronous timeout leaves submission status uncertain; **never retry a live submission blindly**. Persist correlation ID and reconcile status.
- Upstream has unit tests and a separate LTS suite. Its troubleshooting guide notes local validation does not check all iXBRL taxonomy/business rules. Official gateway confirmation remains required.

No exploit testing or live validation performed. This is a source-level risk analysis, not a declaration of a discovered exploitable vulnerability.

## Reproducible first spike

Run `bash scripts/evaluation/ct600_unit_spike.sh` on a Docker-enabled disposable development machine. It pins source SHA, runs only upstream unit tests, and disables network at test-runtime. **Do not provide HMRC credentials, user tax IDs, or genuine financial records.** This test does not contact HMRC.

The script has been syntax-reviewed, but **was not executed** here: this evaluation environment cannot resolve GitHub to clone source and has no Docker daemon.

## What must pass before any live filing

1. Versioned, independently checked accounting data and tax calculations for applicable UK periods.
2. Renderer checks on at least nil, profit, loss, fixed-asset and amendment scenarios using fictional figures.
3. Arelle validation + official HMRC LTS + appropriately authorised real-gateway Test-in-Live acceptance.
4. Submission approval, restricted destination allowlist, tamper-resistant evidence and recovery after timeout/rejection.
5. HMRC permission for the intended user and submission route. Live actions permanently disabled in AI tools until all gates pass.

## Other tests in order

1. **Ledger:** compare GnuCash + export with a database journal using synthetic entries; test balancing, reversals, duplicates, isolation and replay.
2. **Documents:** benchmark Bookcomet with 30+ fictional receipts/statements using local OCR/LLMs only; score extraction and discrepancy rejection.
3. **MTD:** map current 2026 API versions/retirements; use sandbox only; note production restrictions for certain new 2026–27 quarterly-update products.
4. **Companies House:** current software-filing requirements and director approval (not the public read API).

## Authoritative references

- [HMRC Corporation Tax XML developer resources](https://www.gov.uk/government/collections/corporation-tax-online-support-for-software-developers)
- [HMRC MTD Self Employment Business v5.0](https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/self-employment-business-api/5.0)
- [September 2026 HMRC MTD developer newsletter](https://www.gov.uk/government/publications/edition-7-making-tax-digital-for-income-tax-software-developer-newsletter/edition-7-making-tax-digital-for-income-tax-software-developer-newsletter)
- [Arelle CLI](https://arelle.readthedocs.io/en/latest/command_line.html)
- [GnuCash Python bindings & single-writer warning](https://code.gnucash.org/docs/STABLE/python_bindings_page.html)

**Do not merge or enable third-party filing integration until the above is independently tested.** Keep this research PR separate from the unverified personal-foundation PR.

## Continuation: executable qualification checks (9 October 2026)

**Completed locally in the evaluation authoring environment:**
- 9/9 taxonomy acceptance-window tests, using HMRC's 17 April 2026 published limits.
- 8/8 isolated `Decimal` monetary-format tests, including explicit float rejection and rounding policy comparisons.
- 4/4 IRmark tests from the inspected upstream module and test fixture, reconstructed in isolation. This verifies only the hash helper, **not** the entire upstream package.

**Source-level failures/gates discovered:**
- The selected `benhuckvale/ct600-filing` commit hard-codes CT computational taxonomy 2024, which HMRC lists as expiring at **31 March 2026** for accounting period end dates. See [blocker report](CT600_TAXONOMY_BLOCKER_2026-10-09.md).
- Its renderer turns money into `float` before `:.2f`; test inputs `1.005` and `2.675` expose rounding differences from exact Decimal. No universal rounding rule has been assumed.
- The renderer accepts user-supplied tax totals and does not determine whether they are correct. Synthetic diagnostic tests have been added to `test_ct600_contract.py` to document this, but have **not yet been executed against the full upstream clone**.
- Arelle offers an `--hmrc` disclosure-system validation switch, not only generic XBRL validation. A pinned container CLI smoke script is included; **not executed**.
- GnuCash official Python-binding documentation warns about concurrent access/data corruption. This strengthens the case for a transactional PostgreSQL canonical ledger, with GnuCash evaluated primarily for interoperability rather than uncontrolled concurrent writes.

**Still outstanding:** pinned third-party Docker builds, CT600 full upstream/contract suite, official taxonomy packages, Arelle validation, HMRC Local Test Service, Test-in-Live (subject to authorisation), and Bookcomet benchmarking.

Additional tasks: [#6 CT600 qualification](https://github.com/EnigmaThe1/OmniXat/issues/6), [#7 Arelle](https://github.com/EnigmaThe1/OmniXat/issues/7), [#8 Ledger](https://github.com/EnigmaThe1/OmniXat/issues/8), [#9 Document extraction](https://github.com/EnigmaThe1/OmniXat/issues/9).

Sources:
- [HMRC taxonomies accepted, updated 17 April 2026](https://www.gov.uk/government/publications/taxonomies-accepted-by-hm-revenue-and-customs/taxonomies-accepted-by-hmrc)
- [Arelle documented `--hmrc`, `--validate`, `--validationExitCode`](https://arelle.readthedocs.io/en/latest/command_line.html)
- [GnuCash Python-bindings concurrency warning](https://code.gnucash.org/docs/STABLE/python_bindings_page.html)
