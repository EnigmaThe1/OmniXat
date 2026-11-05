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

## Local quarantine staging

`evidence_intake.stage_evidence` is an internal context manager for a blocking
binary source. It validates the declared media type, reads no more than 64 KiB
at a time, stops at the optional declared byte count (or the 20 MiB maximum)
plus one byte, and rejects empty, short or oversized streams. It computes
SHA-256 from the original bytes and rewinds the temporary file for a trusted
scanner to read in bounded chunks. It accepts no client hash, filename or URL.

On POSIX, the spool uses a [Python temporary file](https://docs.python.org/3.12/library/tempfile.html#tempfile.TemporaryFile)
in a pre-provisioned directory owned by the service user with no group or
other permissions (for example, mode 0700). Use a trusted path whose ancestors
cannot be replaced by untrusted users, on a private volume outside any
served path. There is no persistent filename or public URL. The handle closes
on context exit, including read, write or scanner failures. The caller owns
the input stream and must enforce request deadlines and aggregate quotas.

The reader is for trusted scanner integration only. No scanner is wired,
and a staged handle does not certify file format, malware status or durable
storage. Do not register staging metadata alone as proof of a stored file.
Next: add a private tenant-scoped durable quarantine adapter with immutable
object identity, interrupted-write cleanup and tests for retries, then bind
a verified scan decision to those exact stored bytes before extraction.
