# Owner sandbox metrics

`read_sandbox_metrics(connection, actor)` is an internal read service for a
verified, interactive platform owner with MFA. Tenant principals, other staff,
agents and API credentials cannot use it. The service relies on a trusted
server-side principal; it does not implement staff login or a dashboard.

The result is one PostgreSQL statement snapshot. `observed_at` is the database
statement time. Subscription counts are pending, trialing, trial expired and
cancelled. Future starts are excluded; an effective cancellation takes precedence
over expiry. Event counts cover stored simulator receipts received by that time:
matched, price mismatch and state mismatch. These are lifetime counts of distinct
stored tenant/event pairs. An exact retry already reuses its receipt. The
subscription and receipt counts are computed separately so multiple receipts do
not multiply subscriptions. An empty sandbox returns zeros.

There are no tenant filters, identifiers, amounts, customer records or revenue
figures in the result. This is a current sandbox snapshot, with no historical
queries, export, request audit or live billing interpretation.

## Database setup

Apply migration 0007 as the trusted migration owner that owns the sandbox tables.
Grant an unprivileged, dedicated login only database CONNECT, schema USAGE on
`omnixat_metrics`, and SELECT on `omnixat_metrics.sandbox_snapshot`. Use no
role memberships or customer, billing or sandbox schema grants. Keep this login
server side; its credential independently grants access to the aggregate.

The view uses the migration owner's SELECT policies under forced RLS and
projects only counts and a timestamp. The new policies grant no cross-tenant
access to any runtime role. Never grant a runtime membership in the migration
owner or transfer view ownership outside a reviewed migration. The service
requires an exclusive idle autocommit psycopg connection and runs in a bounded
read-only transaction. The view scans sandbox rows at read time; measure cost
before adding polling or exposing an HTTP route.

References: [PostgreSQL 16 views](https://www.postgresql.org/docs/16/sql-createview.html)
and [row security](https://www.postgresql.org/docs/16/ddl-rowsecurity.html).
