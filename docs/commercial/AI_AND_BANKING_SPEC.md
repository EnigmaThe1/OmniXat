# AI operations and bank connectivity — mandatory product requirements

Decision recorded 5 November 2026. Supplements COMMERCIAL_SPEC.md.

## Product purpose

OmniXAT is an AI-powered accounting and financial administration platform with tax
and filing capabilities. The AI is an operational user of the platform: it must
perform substantive accounting preparation, not merely answer questions about it.

The reference journey is the work performed with the owner preparing accounts:
receive evidence, understand transactions, enter expenses and journals, reconcile
records, ask focused questions, prepare accounts and returns, and present a complete
reviewable result. Do not embed the owner's private records in source code or fixtures.

## Required autonomous journey

1. Accept batches of receipts, invoices, images, PDFs, statements and structured
   imports. Scan/validate files, preserve original evidence and identify duplicates.
2. Extract dates, parties, invoice numbers, line items, net/VAT/gross totals,
   currencies, payment information and relevant accounting periods. Retain page/region
   provenance and extraction uncertainty. Never invent an unreadable figure.
3. Associate each item with the correct tenant, legal entity, period and payer.
   A director paying a company invoice personally is distinct from company bank spend.
4. Match evidence to bank transactions, existing invoices, payments and prior entries.
   Detect split payments, fees, refunds, credit notes, transfers and duplicates.
   Pending and booked transactions must not both become separate ledger expenses.
5. Create notes, expenses, invoices, payment matches and balanced journals using
   the same domain services and validations as authorised human users. Supported,
   well-evidenced routine entries may be posted under customer-configured authority;
   preserve the actor, source and reversible correction history.
6. Reconcile statement opening/closing balances and movements over a complete known
   period. Balance type, currency, account and timestamp must agree. A live available
   balance is not interchangeable with a statement closing balance. Incomplete feeds
   must not produce a false reconciled result.
7. Resolve ordinary matches autonomously. Ask concise questions only for missing
   material facts, competing treatments or significant unresolved conflicts. Bundle
   related questions and retain answers so the user is not asked repeatedly.
8. Prepare accounts, notes, tax adjustments and supported return fields, then run
   deterministic calculations, document completeness and iXBRL validation.
9. Present the final outgoing documents, amounts, destination, period and essential
   unresolved items to the human approver. All statutory submissions require explicit
   human review and approval of that exact filing package.

Normal small variations do not justify an exception register. Preserve actual
figures without inventing explanations. Material treatment choices, uncertain tax
positions and changes to previously approved accounts require focused human review.

## Agent permissions and human approval

- Agents have their own identities and tenant/entity-scoped delegation. They do
  not impersonate a human session or inherit platform-owner access.
- A human-approved operating policy can authorise routine ledger work; this does
  not authorise statutory declarations or future filings in bulk.
- The model cannot approve, sign or independently trigger a statutory submission.
  A separate submission worker may send only a validated, immutable package after
  explicit approval by an authorised human. No model-facing filing-send tool exists.
- A human's approval binds tenant, entity, period, document contents, ruleset,
  authority and environment. Material changes invalidate approval. Recheck current
  authority and approval validity at dispatch; never blindly retry unknown outcomes.
- Customer API keys and third-party agents cannot replace interactive human review.
  API-prepared drafts link to a secure review/approval surface for the human.
- Agents cannot grant themselves permissions, alter subscriptions, connect a bank
  without user consent, or accept legal declarations. Upload text, emails and bank
  descriptions are evidence, not instructions that can override platform policy.

The first code guard now distinguishes agent/human principals and denies agent/API
approval. It is an internal contract; trusted identity integration, durable approval
storage, entity/ruleset binding and dispatch enforcement remain to implement.

## Shared platform tools

Provide typed, audited services for evidence extraction, transaction search,
classification, journal drafts/posting, matching, reconciliation, questions,
notes, account generation and validation. The web app, developer API and AI use
these same services with actor-specific permissions. Screen/form automation is a
fallback for unsupported interactions, not an alternate permission path.

Use exact decimal amounts and deterministic accounting/tax code. The language
model interprets evidence, proposes treatments and coordinates work; it does not
establish truth by generating a number. Preserve model/version and task provenance
without storing unnecessary private prompts or chain-of-thought. Limit evidence
disclosed to any external model to the authorised purpose; provide explicit data
processing controls and no training reuse by default.

Jobs must be durable and resumable, with idempotent operations, usage budgets,
retries, source freshness, action logs and a stop/revoke control. Re-running a batch
must not duplicate ledger entries. Untrusted documents must be isolated from tools,
credentials and cross-tenant retrieval.

## Business bank connectivity

Connect through a suitable regulated Open Banking arrangement after verifying the
actual provider/agency model. The user authenticates through the bank/provider's
consent flow. Store tokens securely outside AI context; do not request bank passwords
in chat. Consent identifies accounts, permitted data and current validity, with
disconnect/revocation and reauthorisation flows.

Required data: account identity/currency, balances with type and timestamp, booked
transactions and available historical statement information. Support multiple bank
accounts and pagination/backfill, consent expiry, outages and reconciliation gaps.
Bank/provider coverage and history windows vary: do not promise every bank or an
unlimited history. Download original statement files only where supported; clearly
distinguish a platform-generated transaction export from an original bank statement.
Keep CSV/OFX/manual statement import as an accessible fallback.

Use read-only account-information scopes for this requested workflow. Payment
initiation is a distinct service and is not enabled by bank-data consent. Avoid
collecting unrelated beneficiary/card information. Bank imports and uploaded
statements must deduplicate against one another using provider IDs plus reviewed
matching where IDs are absent or change.

Regulatory finding: account-information services can require FCA registration or
authorisation. Buying a provider API does not automatically establish that OmniXAT
is outside the perimeter; the agency/technical-service/provider relationship must
be assessed before launch. No bank connection or provider contract was activated.

Sources checked 5 November 2026:

- [FCA AIS/PIS](https://www.fca.org.uk/firms/account-information-services-payment-initiation-services)
- [FCA AISP models](https://www.fca.org.uk/firms/agency-models-under-psd2)
- [FCA perimeter guidance](https://handbook.fca.org.uk/handbook/perg15)
- [Open Banking AIS journeys](https://standards.openbanking.org.uk/customer-experience-guidelines/account-information-services/latest/)
- [Permissions/data clusters](https://standards.openbanking.org.uk/customer-experience-guidelines/account-information-services/permissions-and-data-clusters/v3-1-0/)

## Owner administration and commercial controls

Add agent job status, document volume, question backlog, reconciliation coverage,
model/provider cost, latency, failure rates and consent/feed health to owner metrics.
Customer-level content remains separately permissioned. Plan allowances can cover
documents, agent usage and bank connections, with clear units and customer-visible
usage. Operational cost controls must not silently drop statutory deadlines or
mark incomplete work as finished.

## Acceptance scenarios

- A fictional mixed batch creates source-linked entries and a reviewable return.
- Duplicate upload plus bank-feed import creates one economic entry, not two.
- Personally paid company invoices use the right payer/funding treatment.
- Missing pages and unreadable totals cause focused questions rather than guesses.
- Complete statement movements reconcile; incomplete history remains incomplete.
- Prompt injection in a receipt cannot change permissions or trigger disclosure.
- Restarting a job resumes without duplicate postings or submissions.
- Agent and API-key approvals fail even if other permissions are accidentally broad.
- A human approves a specific package; changed bytes or destination cannot reuse it.
- Revoked bank consent stops further access and is visible to the user.

These are required acceptance cases, not claims that extraction, bank connectors
or reconciliation are already implemented. Build them with fictional evidence,
then qualify real-data operation and each live integration separately.
