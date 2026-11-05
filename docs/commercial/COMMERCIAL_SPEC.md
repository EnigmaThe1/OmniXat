# OmniXAT commercial product specification

Decision baseline: 5 November 2026. This supersedes deferral of commercial multi-tenancy, billing and API subscriptions in earlier planning. This is a target architecture, not a claim that the features below already exist.

## Product surfaces

1. **Customer workspace:** people, organisations, records, books, accounts, tax, calendar, evidence, approvals, submissions, subscription and exports.
2. **Developer platform:** versioned API, sandbox, scoped credentials, usage and quota dashboard, documentation, idempotency and signed webhooks.
3. **Owner control centre:** platform metrics, customer lifecycle, plans/prices, API operations, filing health, support, staff access and compliance administration.

One service layer serves the web app and developer API. Never duplicate tax calculations in the frontend. Each feature has independent statuses for records, calculation, export, sandbox filing and live filing. Unsupported scenarios cannot be unlocked through a paid plan.

The AI must operate these services autonomously for evidence intake, ledger entries,
notes, questions, reconciliation and document preparation. Business bank connectivity
is a required capability. Human review and explicit approval remain mandatory for
every statutory submission. See [AI and banking requirements](AI_AND_BANKING_SPEC.md).

## Customer and identity model

- Tenant/workspace is the customer data boundary; taxpayer/legal entity is a separate concept.
- Users can belong to several tenants, but every request runs in exactly one verified membership context.
- A person can have multiple businesses and company roles. Taxpayer records are not login accounts.
- Accountants receive explicit client-workspace membership/delegation; their practice tenant does not implicitly own clients' records.
- PostgreSQL is the target canonical database. Require tenant IDs, composite foreign keys and database row-level policies as defence in depth; use a non-owner runtime role. Object storage, caches, search, job queues, logs and backups need equivalent scoping.
- Use a maintained identity provider with verified email, MFA/passkeys, secure recovery and revocable sessions. Do not promote the demo password/session flow or browser tenant selector to production authentication.
- Roles are permission bundles. Initial customer roles: owner, editor, viewer; separate filing approver and billing rights can be delegated later. Unknown permissions deny by default.
- API principal combines verified membership, entity grants and scopes. A customer-selected role header is never trusted.

## Owner administration

Staff identities/permissions are separate from customer membership. A platform-owner role is not blanket permission to view tax records. Support access must be explicitly authorised, time-limited, reason-coded and logged; sensitive exports require additional permission.

| Section | Requirements |
|---|---|
| Overview | Customers, active/trial/past-due subscriptions, sign-ups, cancellations, service incidents and processing backlog |
| Revenue | MRR/ARR, collected revenue, refunds, failed payments, plan mix and churn; definitions and currency displayed |
| Customers | Membership, plan, lifecycle and service state; confidential content separately permissioned |
| Plans/prices | Editable trial duration, feature entitlements, allowances and versioned GBP prices; scheduled publication and audit |
| Billing operations | Hosted payment-provider references, reconciliation, invoices and controlled refunds; no raw card storage |
| API | Usage per tenant/key/route, quotas, throttles, latency, errors and credential revocation |
| Filing operations | Counts by authority, environment, module and pending/accepted/rejected/unknown state; no confidential payload in overview |
| Compliance | Source/rule review queue, module qualification evidence, retention holds, rights requests and incidents |
| Staff | Owner, supervisor, billing administrator and support permissions, MFA, session revocation and access review |
| Reports | Permission-scoped exports with explicit period, definitions and data freshness |

Metrics must avoid double counting. MRR is normalised recurring subscription value, not total cash receipts; exclude tax, one-off fees and refunds according to the approved metric definition. API usage must distinguish requests, billable units, retries and failed calls. Customer churn and revenue churn are separate. Aggregate views should reveal only what staff need.

## Plans, trials and payment lifecycle

Plan, price version, entitlement version and subscription are separate records. A subscription pins agreed versions; publishing a new price does not alter existing contracts or invoices. Support monthly/annual pricing, sandbox/API allowances and scheduled changes. Prices and trial length remain configurable; no real commercial price is chosen in the code spike.

Trial, active, past_due, grace, canceled and expired states must be driven by verified provider events and reconciliation. A checkout success redirect is not proof of payment. Verify signatures before processing webhooks; deduplicate provider events, handle reordering, and use an outbox for downstream effects. Refunds and contract changes need authorised staff roles. A billing outage must not delete records or misreport filing outcomes.

Trial-to-paid terms, customer notices and subscriber migrations must be reviewed before activation. Preserve export/retention rules on cancellation. Statutory submission fees are separately disclosed; they are not silently included in arbitrary API charges.

## API contract direction

Proposed `/v1` resources: organisations, people, evidence, transactions, accounts, obligations, calculations, filing-drafts, approvals, submissions, receipts, usage and webhooks. `/admin/v1` is an independently protected staff surface. These are proposed routes, not implemented HTTP endpoints.

- Tenant-bound, revocable credentials; store only suitable verification material for API secrets.
- Scopes and entity grants checked on every object and job. API access never bypasses customer filing approval.
- Idempotency scoped by tenant, operation and request digest. Different payloads under the same key conflict.
- Stable error codes, pagination, request IDs, rate limits and documented version/deprecation policy.
- Signed outbound events, delivery IDs, retries and replay controls. Avoid confidential data in webhook payloads by default.
- Strict egress controls for customer-configured webhook destinations to prevent SSRF.
- Downstream filing retains required end-user fraud-prevention context; headers are not invented.
- Sandbox uses fictional data and separate credentials, storage, quotas and capability labels.

## Ledger and compliance engine

Use exact decimal monetary values, double-entry invariants, explicit rounding rules and deterministic calculations. Preserve source provenance and corrections. Distinguish accounting adjustments from tax adjustments and recipient-specific document outputs. Never let an AI assistant change statutory rules, post uncertain extracted entries or approve its own filing.

Rules are versioned by legal/technical effective basis: tax year, accounting-period start/end, transaction date or submission date as appropriate. Preserve original rules/data snapshots when producing amended documents. Draft calculations cannot silently become official liabilities.

Submission state: draft → validated → awaiting approval → approved → queued → submitted/pending → accepted/rejected/unknown. Approval binds artifact hash, tenant/entity, destination, environment and ruleset. A material change invalidates it. Production submission must recheck actor authority, expiry/revocation, module qualification and exact bytes. Unknown outcome requires reconciliation before retry. No automatic filing merely because a subscription permits it.

## Development milestones

| Milestone | Deliverable | Required proof |
|---|---|---|
| C0 — started | Rules catalogue and tested internal access, pricing and approval contracts | Offline behavioural tests and clear unsupported boundaries |
| C1 | PostgreSQL migrations, identity adapter and per-tenant repositories | Integration tests for cross-tenant reads/writes, object grants, recovery and migration |
| C2 | Shared customer/API services and owner administration | Verified role matrix, staff isolation, accurate aggregate metrics and audit |
| C3 | Hosted billing sandbox, persistent prices/entitlements and quotas | Signed/deduplicated events, reconciliation, cancellation/export and unchanged old prices |
| C4 | Ledger, evidence intake, reconciliation and ordinary/revised document engine | Independent reference cases, source traceability and document validation |
| C5 | Qualified authority adapters, one module at a time | Current official specifications/test evidence, approval integrity and live-access eligibility |
| C6 | Controlled commercial launch | Security/accessibility review, restoration rehearsal, service classification and customer terms |

Research covers broad entity types; release support expands by qualified module. No commitment to universal filing support or launch date is made. Public deployment, payment activation, legal declarations and publication of new proprietary work require their appropriate release approvals.
