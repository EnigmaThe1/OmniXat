# PostgreSQL agent-job checkpoints

Migration 0051 and `omnixat_core.jobs_postgres.PostgresJobStore` persist the
existing development job interface through the shared PostgreSQL transaction
boundary. Construct the store with an exclusive idle autocommit psycopg
connection. Call `create`, `get`, `claim` and `checkpoint` with a server-verified
tenant Principal and tenant UUID string. Methods return the same string job/token
IDs and `id`, `status`, `checkpoint` read shape as the SQLite development contract.

## Storage and access

Provision a non-owner NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOCREATEROLE login.
Grant only USAGE on `omnixat` and SELECT, INSERT, UPDATE on
`omnixat.agent_jobs`.
Use the existing explicit migration runner with separate migration credentials.

Each method checks permission, role safety and forced RLS, binds transaction-local
tenant context and commits or rolls back before returning. Reads are READ ONLY.
Human and agent editors can create, claim and checkpoint with records write
permission. Viewers require records read permission. API scopes further restrict
those permissions. Platform staff have their separate access boundary.

The application must resolve current membership/revocation before supplying a
Principal. A raw runtime credential can set tenant context and issue arbitrary
SQL within its grants. These grants trust the application SQL boundary, as the
existing records repository does. Production identity and operational qualification
remain release requirements.

## Retries and worker recovery

Creation hashes the JSON payload with the development adapter's canonical
serialization. Only that SHA-256 and the bounded tenant-scoped request key are
stored, alongside the creator and timestamp. Identical concurrent retries return
the original ID. Changed payloads under the same key raise ValueError. Original
attribution survives retries by other authorised tenant editors.

Claims lock the job before checking the database clock. A queued or expired
running job receives a fresh lease token, verified worker ID and lease expiry.
The configurable lease is 1–3600 seconds, default 60. A checkpoint requires that
same worker, live token and unexpired lease after row-lock acquisition. A replaced
or expired worker cannot overwrite or complete the job. This worker binding is an
additional restriction in the PostgreSQL adapter.

Progress is a JSON object bounded to 65,536 encoded bytes, with a database size
check too. Use opaque evidence/record references and minimal step metadata.
Successful progress renews the lease for 60 seconds, matching the development
contract. Completion stores final progress and clears the token and expiry.
Completed jobs cannot be claimed again. The database clock is authoritative.
After an uncertain checkpoint response, read the saved state before choosing a
retry. Creation replay and checkpoint-result reconciliation have distinct roles.

Checkpoint storage and individual domain effects have separate transactions.
Ledger effects still require operation-specific idempotency and atomic/outbox
boundaries. Lease recovery can repeat work since the last checkpoint. Worker
scheduling, membership revocation, retry budgets, effect fencing and transport
wiring remain unfinished. Existing SQLite stores retain their development scope.

## Verification

Use the disposable PostgreSQL test setup in POSTGRES.md. The integration suite
exercises actual constrained roles, concurrent creation/claim races, persistence,
expired/replaced worker fencing, lock-wait expiry, tenant isolation, validation and
rollback. Fictional references suffice. Worker execution requires separate
explicit orchestration.

Technical semantics rechecked on 7 November 2026 against PostgreSQL 16
[transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html)
and [database time functions](https://www.postgresql.org/docs/16/functions-datetime.html).


## Cancellation

Migration 0052 adds `cancel(actor, tenant, job_id)`. It uses the same tenant
records-write permission and API-scope checks as job creation. Authorised human
and agent editors may cancel queued or running preparation. The method returns
an immutable `JobCancellationReceipt` with job ID, first cancelling actor and
database timestamp. Retries by authorised tenant writers return that first receipt.

Cancellation locks the job against claims and checkpoints, preserves the last
progress and worker attribution, and clears the live token and expiry. Subsequent
claims and checkpoints fail. A completed job retains its terminal state. Concurrent
cancellation and completion serialize on the row, with the first committed terminal
transition determining the result. `get` exposes `cancelled` using its existing
response shape. Creation-key replay continues to identify the cancelled job.

Cancellation controls job preparation state. External work already in flight and
committed domain effects require their own cancellation/fencing and reconciliation
contracts. Operation-specific effect idempotency remains the next implementation
step. Apply the migration before using cancellation. Existing job-role grants
cover the added columns.

PostgreSQL 16 row-lock semantics rechecked on 7 November 2026 against
[explicit locking](https://www.postgresql.org/docs/16/explicit-locking.html).
