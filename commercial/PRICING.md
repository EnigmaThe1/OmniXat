# PostgreSQL price catalogue

The internal staff service in `omnixat_core.pricing_postgres` stores platform plans
and immutable GBP price versions. It has no HTTP route and makes no payment
requests. No plans or prices are seeded by the migration.

- `register_plan` adds a stable plan code and display name.
- `create` adds a new version with an integer minor-unit amount, monthly or annual
  interval, trial days, API allowance and timezone-aware effective date.
- `effective` resolves the latest version on or before a supplied instant for one
  plan and interval. Two versions cannot share that instant in the same series.
- `get` retrieves a specific version by ID so future subscription records can pin
  agreed terms. Creating another price never mutates that version.
- `audit` gives platform owners a bounded, per-plan history of registrations and
  price creation, with operation, result ID, verified actor ID and timestamp. The
  event metadata is written with the record, so a failed write leaves no event.

Owners and billing administrators need an MFA-verified, interactive human staff
principal. Only owners can call the audit method. Customer membership, API tokens
and agent principals do not provide staff authority. The caller must supply a
trusted staff principal; browser staff sign-in, role assignment and step-up
qualification are not implemented here.

## Database setup

Apply additive migration 0004 with the migration owner. Give a separate,
non-owner pricing login `USAGE` on `omnixat_billing` and `SELECT, INSERT` on
`omnixat_billing.plans` and `omnixat_billing.price_versions` only. Do not give it
membership in customer, owner or migration roles, or rights on the customer
schema. Keep all billing grants away from the customer login. No RLS is required
for the global catalogue: its schema is private to the separate service login.
Use an exclusive idle autocommit connection with bounded acquisition.

The service rejects superusers, bypass-RLS identities, role-switched connections,
customer schema access, catalogue ownership and update/delete/truncate grants on
catalogue tables. The application enforces staff permissions; trusted database
operators can still administer these tables and must restrict access. This audit
is record provenance, not an independently tamper-proof security log.

## Limits and verification

Effective dates support scheduling but do not implement a publication approval
workflow, price change notifications, catalogue retirement or backdating policy.
There are no subscriptions, invoices, entitlements, metering, provider credentials
or live payments. Do not use this service to activate billing. A later sandbox
can pin versions and exercise verified, deduplicated provider events separately.

On 5 November 2026, 32 core, 9 token and 76 PostgreSQL/HTTP integration tests passed
with fictional data. The PostgreSQL suite uses a disposable cluster as described
in [POSTGRES.md](POSTGRES.md). It exercises separate grants, staff permissions,
price history, scheduled selection, duplicate rejection and audit attribution.

Primary reference: [PostgreSQL 16 schema privileges](https://www.postgresql.org/docs/16/ddl-schemas.html).
