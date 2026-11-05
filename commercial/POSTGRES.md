# PostgreSQL record persistence — C1 first slice

This adapter persists tenant organisations and attributed notes. It is not an
identity service, full ledger, evidence extractor or production-qualified deployment.
The SQLite job adapter remains unchanged and separate.

## Installation and migration

Python 3.11+; PostgreSQL 16+ target. Integration exercised on temporary PostgreSQL
16.2 with psycopg 3.3.8. Repeat on the maintained production version before release.

```bash
cd commercial
python3 -m pip install -r requirements-postgres.txt
```

Invoke `omnixat_core.postgres.migrate(connection)` explicitly with a dedicated
migration owner and an idle autocommit psycopg connection. It takes a transaction
advisory lock, applies SQL and version records atomically and verifies SHA-256
checksums on repeat calls. Applied SQL files are immutable; add new numbered
migrations. Unknown versions or missing/changed files fail. Do not run migrations
on application startup or pass migration credentials to runtime workers.

Provision a distinct runtime LOGIN role with NOSUPERUSER, NOBYPASSRLS, NOCREATEDB
and NOCREATEROLE. It must not own tables or belong to an owner/migration role, nor
have CREATE on `public` or `omnixat`. Supply credentials through the deployment's
secret mechanism. For that role grant only:

- CONNECT on the selected database and USAGE on schema `omnixat`.
- SELECT on `omnixat.tenants`.
- SELECT, INSERT on `omnixat.organisations` and `omnixat.notes`.

No UPDATE, DELETE, TRUNCATE, DDL or migration-table privileges are required. Tenant
provisioning is a separate administrative operation; no public signup endpoint is
implemented. Never run the customer repository as the migration owner.

## Service boundary

Use `tenant_records(connection, verified_principal, tenant_uuid, write=False)`.
Each unit of work requires an exclusively leased idle autocommit connection; it
starts a transaction, checks active row security/role safety and binds the tenant
with transaction-local `set_config`. Read units also use database READ ONLY.
Normal exit commits; exceptions roll back; the repository cannot be reused after
exit. Nested transactions/units are rejected. Return the connection to its pool
only after exit, and never share it across concurrent workers.

Within the block use `create_organisation`, `get_organisation`, `create_note` and
`get_note`. Names/bodies are bounded by database checks. Notes require an existing
same-tenant organisation; composite keys enforce that relationship. Actor IDs come
from the verified principal. Every query includes tenant predicates and forced RLS
also blocks unscoped reads and foreign-tenant inserts. No-context reads return no
rows. Viewer/API scope/staff restrictions use the existing shared permission code.

This trusts the server's Principal and SQL execution boundary. A caller with raw
runtime credentials can select a different tenant context; RLS does not authenticate
customers or protect a compromised server. The optional [identity adapter](IDENTITY.md) now provides persistent membership and
revocation checks for signed bearer access. Entity grants, maintained-provider login
and transport integration are still required before HTTP,
web or developer API exposure. Notes do not grant filing approval or financial
posting authority. This slice has no retries/idempotency keys for record creation;
AI job retries must not call it as an exactly-once ledger service.

## Integration tests

Use a disposable local PostgreSQL cluster. Set `OMNIXAT_TEST_ADMIN_DSN` through the
environment to an administrative connection with database/role creation rights.
The suite creates a random `omnixat_test_*` database and constrained login, connects
as that login for repository operations, and drops both during cleanup. Never use
production credentials or a production cluster for this suite. An interrupted test
may leave its random test database/role for manual cleanup.

```bash
cd commercial
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s integration_tests -v
```

The integration suite fails clearly without its DSN/dependency; no tests are silently
skipped. It verifies actual PostgreSQL RLS and privileges, cross-tenant references,
permissions, agent attribution, rollback, reconnect, connection reuse, read-only
transactions, ended/nested units, owner-role membership and migration integrity.
The core suite remains dependency-free. The historical demo/browser suite is separate.

## Technical sources checked 5 November 2026

- [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [PostgreSQL CREATE POLICY](https://www.postgresql.org/docs/current/sql-createpolicy.html)
- [Transaction-local settings](https://www.postgresql.org/docs/current/functions-admin.html)
- [Psycopg transaction contexts](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)

These sources informed the engineering implementation. No legal rule or live filing
capability was added or changed in this increment.

## Additive membership migration

`0002_identity_memberships.sql` builds on immutable migration 0001. Runtime access
for the identity adapter also needs SELECT on `omnixat.identities` and
`omnixat.memberships`; no write/DDL grant. Current integration suite has **37 tests**.
See [IDENTITY.md](IDENTITY.md) for trust configuration and revocation semantics.
