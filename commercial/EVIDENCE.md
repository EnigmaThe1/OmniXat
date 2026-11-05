# PostgreSQL evidence registry

Migration 0013 introduces metadata registration for the future document intake
service. Each record identifies a tenant organisation, a SHA-256 content
fingerprint, declared media type, byte count and first registrar. No file
bytes, filename, storage locator, extracted value or external URL is stored.
A registration alone is not proof of a stored, valid or malware-free file.

Call `register_evidence` only from a trusted intake service that determines
the fingerprint and size from the original bytes. Never register a digest
asserted by a browser, API client or model. Identical fingerprints and
metadata in the same organisation return the first committed record, even
when requests race. A conflicting media type or size is rejected and does
not change the original. Identical data elsewhere creates separate records.

Owner and editor tenant principals may register; agents, staff principals
and current records bearer scopes cannot. Owner, editor and viewer principals
can read scoped metadata with `get_evidence`, subject to any explicit scopes.
No route or bearer scope is added. Organisation-specific grants are not yet
implemented within a tenant.

Apply migrations as the migration owner. For a non-owner, non-BYPASSRLS
runtime grant schema USAGE, SELECT on organisations and SELECT/INSERT on the
evidence table; do not grant UPDATE, DELETE or TRUNCATE. The registry uses
forced row security, a composite organisation foreign key, and an exclusive
idle autocommit connection per unit of work. The existing verified principal
boundary still applies; row security is not a defence against a compromised
SQL runtime setting a different tenant context.

The development metadata allowlist is PDF, JPEG, PNG and CSV, up to 20 MiB.
This is an intake bound, not file-format validation. Next: stage original
bytes through a private object-store adapter, verify the fingerprint while
streaming, and keep unscanned objects quarantined. Model extraction should
consume verified evidence references, not fetch arbitrary user-supplied URLs.
Retention and correction workflows, source-page references, ledger writes and
filing are outside this increment.

References: [PostgreSQL 16 row security](https://www.postgresql.org/docs/16/ddl-rowsecurity.html)
and [conflict handling](https://www.postgresql.org/docs/16/sql-insert.html).
