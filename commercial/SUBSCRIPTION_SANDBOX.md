# Tenant subscription sandbox

This is an internal PostgreSQL service for fictional billing exercises. It has no
HTTP route, provider credentials, payment requests, renewals or live entitlements.
No subscriptions are seeded by migration 0005.

- `start` chooses the effective version for the requested plan and interval at
  the trusted server clock, and stores its ID. Repricing does not change the
  stored price, allowance or trial deadline.
- A positive configured trial starts in `trialing` and reaches `trial_expired`
  at its deadline (configured days are 24-hour days measured in UTC). A price
  without a trial starts in `pending`. Neither state becomes paid or active.
- `cancel` records a cancellation of a pending or trialing subscription. Repeating
  cancellation returns the existing outcome. Cancelled takes precedence over
  later trial expiry. The recorded time comes from the service clock.
- There is one sandbox subscription per tenant, including after expiry or
  cancellation. A duplicate start conflicts and can be reconciled using `get`;
  this model does not reset trials or support switching and multiple products.

The caller supplies an already-verified interactive tenant owner with MFA.
Bearer, agent, staff, unverified, editor and cross-tenant principals cannot
manage these subscriptions. This does not implement customer login or consent.
Status is a sandbox calculation, not proof of payment or a live entitlement.

## Database grants

Apply migration 0005 as the migration owner. Grant a dedicated, non-owner runtime
login `USAGE` on `omnixat_sandbox`, `SELECT` on `omnixat_sandbox.price_terms`,
and `SELECT, INSERT` on `omnixat_sandbox.subscriptions` and
`omnixat_sandbox.cancellations`. Give it no customer or billing schema access,
no other role memberships, and no UPDATE, DELETE or TRUNCATE grants. Do not grant
customer or staff catalogue logins access to the sandbox schema.

Both tables use forced tenant row-level security and a tenant-bound cancellation
reference. The narrow price view exposes terms without catalogue staff attribution
or write grants. The runtime checks role/ownership and grants, but a trusted SQL
runtime that can set its own tenant context is not an independent authentication
boundary. Creation and cancellation rows retain minimal actor/time provenance.

Use an exclusive, idle autocommit psycopg connection with bounded acquisition.
The same tenant transaction limits as the record service apply. No schema change
is made to the price catalogue. A separate [local simulator receiver](SANDBOX_EVENTS.md)
can record comparison receipts without changing these subscriptions.

## Verification and follow-up

On 5 November 2026, 32 core, 9 token and 84 PostgreSQL/HTTP tests passed using
disposable PostgreSQL 16.2. Eight new sandbox tests cover price pinning, trial
boundaries, cancellation replay, permissions, separate grants and tenant-bound
references. The original demo Chromium prerequisite is unchanged.

The local simulator contract is documented in [SANDBOX_EVENTS.md](SANDBOX_EVENTS.md).
Keep external connections, activation and paid contracts gated. No product or legal trial terms are implied.

Primary references: [PostgreSQL 16 views](https://www.postgresql.org/docs/16/sql-createview.html)
and [row security](https://www.postgresql.org/docs/16/ddl-rowsecurity.html).
