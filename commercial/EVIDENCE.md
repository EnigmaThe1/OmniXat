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
This is an intake bound, not file-format validation. Verify the fingerprint
while streaming and keep unscanned objects quarantined. Model extraction should
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

## Durable PostgreSQL quarantine

Migration 0014 adds a separate quarantine table. The internal
`store_quarantined_evidence` operation accepts an unconsumed staged original
and an existing evidence ID. It checks tenant, organisation and registration
metadata before consuming bytes, and verifies the digest again. PostgreSQL
computes the digest and size independently and requires an exact match to the
registration through a composite foreign key. The immutable object identity
is the tenant/evidence pair. A matching retry from a fresh staging context
returns the original receipt, including under concurrent requests.

Use a non-owner runtime that cannot bypass row security. Grant schema USAGE,
SELECT on evidence registrations, and these column grants on quarantine:

- INSERT on `tenant_id, evidence_id, original_bytes`.
- SELECT on `tenant_id, evidence_id, stored_at`.

The store rejects roles with SELECT on the payload or UPDATE, DELETE or
TRUNCATE on quarantine. It returns only evidence ID and storage timestamp.
Quarantine bytes and receipt are written atomically; a failed transaction
leaves no standalone payload or object key to clean up. A metadata
registration may still exist before storage and is never a storage receipt.
This adapter buffers one verified original (at most 20 MiB) for a single
binary SQL parameter. It is not a streaming external store and does not
enforce aggregate storage or worker concurrency limits.

Before real use, qualify storage and backup encryption, payload-free database
logging, capacity, retention and restore. See [PostgreSQL binary functions](https://www.postgresql.org/docs/16/functions-binarystring.html).

## Scanner-only verdicts

Migration 0015 records append-only `clean` or `blocked` observations tied by
foreign key to the tenant, evidence ID, digest and size of the quarantined
original. A trusted worker calls `scan_quarantined_evidence` with scope from
its job and a server-selected scanner and policy version. The policy version
must identify an immutable scanner configuration, including its engine and
rules or signatures. Use a new version for a rescan after configuration changes.

The worker reads only the requested tenant/organisation/evidence, verifies the
bytes and calls the scanner outside the database transaction. Scanner failures
or unknown results create no verdict. Replay for the same version returns the
recorded result without calling the scanner again. If legacy observations
disagree, reads prefer `blocked`. A receipt is a point-in-time observation,
never authority to extract.

Use a separate non-owner, non-BYPASSRLS scanner login. Grant schema USAGE,
SELECT on the evidence registration, quarantine and verdict tables, and
INSERT on verdict columns `tenant_id, evidence_id, content_sha256, byte_size,
policy_version, verdict`. Do not grant mutation of originals or existing
verdicts. Do not reuse intake or customer credentials. These are internal
worker grants; the login must not be exposed to a model, HTTP client or
general query interface. As elsewhere, RLS protects against missing predicates
under an established context, not a compromised worker setting its own context.

## Recoverable scan claims

Migration 0016 adds a single claim per tenant, evidence ID and scanner policy
version. Grant the scanner login SELECT, INSERT and DELETE on
`omnixat.evidence_scan_claims` and UPDATE only on `lease_token, expires_at`.
Do not grant claim access to intake or customer roles.

The scanner commits a claim before calling the engine. A competing worker
gets `EvidenceScanBusy` while the claim is live. The fixed 120-second lease
uses the database clock; a later attempt can replace an expired claim.
Completion records the verdict and removes the live claim in one transaction.
An expired or replaced worker cannot publish or clear a replacement's claim.
Failures release the worker's own claim when possible; if the process or
database connection is lost, retry can recover once the lease expires.

This is an on-demand claim, not a scheduler or exactly-once execution. The
engine must have its own deadline shorter than the lease; expiration does not
stop a running engine, and two executions can overlap after expiration. No
real scanner is qualified. A deployment still needs worker isolation,
bounded retries and monitoring.

## Extraction admission

Migration 0017 creates a private active-policy table and an execute-only read
function. The policy table starts empty, which disables admission. A trusted
operator configures the singleton policy after qualification; no worker or
customer selects a policy on a read. In one database statement the function
requires a clean observation for the exact bytes under that policy, no
blocked observation for the same policy and no live claim. Old policies do
not authorise a read. The Python adapter also verifies SHA-256 and byte
length before handing the original to trusted worker code.

Give the gate login USAGE on `omnixat_extraction` and EXECUTE on
`omnixat_extraction.read_eligible_original(uuid, uuid)` only. Do not grant
raw table access or expose the login to an extractor, model or HTTP client.
Use a trusted job's tenant, organisation and evidence IDs. The function
checks tenant context explicitly but does not authenticate it; the worker
that establishes context must enforce job authorisation. Keep the function
owner and policy administration separate from worker logins.

Admission is a point-in-time read, not a revocation mechanism for bytes
already handed to a worker. No extractor runs. Next: qualify a scanner
and wire a bounded, isolated extraction worker with source provenance,
retry controls and an active-policy recheck before persisting results.

## Bounded CSV amount extraction

The internal `extract_csv_amounts` worker reads only an admitted
`text/csv` original and accepts explicit, named cell selections. Every
result references the evidence ID, exact SHA-256, scan policy and one-based
logical record and column; headers count as records and quoted newlines do
not start a new record. It accepts comma-separated UTF-8 with optional BOM,
up to 512 KiB, 5,000 records, 64 columns, 4,096 characters per cell and 32
selections. No format detection, formula evaluation or network is involved.

The reader uses exact decimal arithmetic for an optional sign, up to 18
integer digits and up to six fractional digits separated by a period.
Surrounding ASCII spaces and tabs are ignored. A missing, blank or ambiguous
cell returns a distinct status and no amount; the reader does not infer
currency or interpret grouped numbers, locale-specific separators or
exponents. Values are candidates for review, not ledger entries.

The read-only worker can return candidates in memory. For durable storage,
`extract_and_store_csv_amounts` accepts a stable server-assigned job ID and
stores the source fingerprint, policy and versioned parser results, including
decimal strings and original cell coordinates. Migration 0018 adds an
append-only, tenant-isolated table with no direct worker access. Grant
the existing execute-only extraction login EXECUTE on
`omnixat_extraction.store_csv_result(uuid,uuid,uuid,text,bytea,jsonb)` only
in addition to the existing admission grants. It is a trusted job boundary,
not a client-facing write API.

The write function checks eligibility again and locks the active policy row
against rotation until commit. It refuses stale results, returns the first
receipt for an identical retry, and rejects reuse of the job ID for a
different result. A new extraction under a changed policy needs a new job
ID. Previously committed results remain historical; a future consumer must
recheck eligibility before using them. No OCR, model, public route or ledger
effect is wired.

## Scoped CSV review

Migration 0021 lets a dedicated review login read one result with answers
through `omnixat_extraction.read_csv_review_with_answers(uuid,uuid,uuid)`.
Grant that function and USAGE on `omnixat_extraction` only; revoke the old
`read_csv_review` grant from the review login if present. Keep it separate from the
extraction worker and give it no raw schema access. The application service
requires a verified interactive tenant user with evidence read permission.
The database checks tenant, organisation, evidence and job ID and reuses
the active-policy gate at read time. It returns structured candidates and
provenance without raw source bytes or original cell text.

The service prepares fixed questions only for missing, blank and ambiguous
cells without a saved answer. It does not send questions. A review is a
point-in-time read; any future accounting write must recheck eligibility.

## Durable clarification answers

Migration 0020 lets an interactive tenant owner or editor record one answer
against an unresolved extraction field and its exact job and cell. An exact
decimal string retains its scale; explicit null records that the amount is
unavailable. The answer is attributed to the verified user. An identical
retry by that user reuses the receipt, and a different answer conflicts.

Grant the dedicated answer login USAGE on `omnixat_extraction` and EXECUTE on
`omnixat_extraction.store_csv_answer(uuid,uuid,uuid,text,integer,integer,text,text)`
only. Keep it separate from the review and extraction logins. The write
function checks current eligibility and holds the active policy until commit.
It does not modify extraction results. Review shows each answer, its
author and timestamp separately, without rewriting the original candidate.
An unavailable answer suppresses the repeated question but supplies no
amount for accounting. Neither the answer nor the review posts a ledger entry.

## Source-linked accounting draft amounts

Migration 0022 stores one draft amount for an exact extraction job and field.
An interactive tenant user with evidence read and records write permission
selects a cell. PostgreSQL derives the exact decimal from the extracted value
or its attributed clarification; callers cannot supply an amount. Unanswered
or unavailable cells are refused. The write checks current eligibility and
holds the active policy until commit. An identical retry by the same actor
returns the original receipt.

Grant a dedicated draft login USAGE on `omnixat_extraction` and EXECUTE on
`omnixat_extraction.create_csv_draft_amount(uuid,uuid,uuid,text,integer,integer,text)`
only. The source link is the immutable extraction job and cell; the draft
records whether its value was extracted or clarified. This stores an amount
candidate only. It assigns no currency, accounting date, account or tax
treatment and cannot post to the ledger.

## Scoped draft amount reads

Migration 0023 adds `read_csv_draft_amount` for interactive tenant users
with evidence read permission. The caller selects an exact organisation,
evidence, extraction job and cell. The read rechecks the active policy and
source eligibility and returns the exact decimal, source kind, digest,
creator and timestamp. Stale or mismatched requests return no draft.

Give the dedicated reader login USAGE on `omnixat_extraction` and EXECUTE on
`omnixat_extraction.read_csv_draft_amount(uuid,uuid,uuid,text,integer,integer)`
only. Keep it separate from draft, answer and extraction writers. This
read neither validates accounting context nor authorises ledger effects.
