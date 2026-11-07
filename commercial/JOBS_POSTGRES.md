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
scheduling, membership revocation, effect fencing and transport
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

## Fenced note preparation

Migration 0053 adds `create_note_effect(actor, tenant, job_id, token,
operation_key, organisation_id, body)`. This operation uses the existing
`TenantRecords.create_note` validation, parent checks and record audit. It commits
the note, record audit and job-scoped operation receipt together while holding
the job lock. Current verified worker, token, running state and database lease
are checked after lock acquisition and again after preparing the result.

Use a stable operation key of 1–128 ASCII letters, digits or `._~-` per tenant
and job. Its digest and the exact organisation/body digest identify the operation.
The returned `JobNoteReceipt` contains job, note and organisation IDs plus original
actor and timestamp. Concurrent identical retries return one receipt. A recovered
worker with a fresh valid claim can replay the original operation and attribution.
Changed inputs under the same key raise `CreationConflict`. A saved note that has
changed also conflicts. Terminal jobs reject effect calls, including receipt replay.

The worker requires both records write and records read permission, with matching
API scopes where applicable. Add SELECT on `omnixat.tenants` and
`omnixat.organisations`, and SELECT, INSERT on `omnixat.notes`,
`omnixat.record_creations` and `omnixat.agent_job_note_effects` to its job grants.
These grants share the existing application SQL trust boundary. The method checks
active RLS and non-owner role safety for every participating table.

Job progress is checkpointed separately. After recovery, reusing the same operation
key reconciles a note committed before the last saved progress update. Cancellation
and note preparation serialize on the job lock. A note committed before cancellation
remains part of preparation history. Expiry during preparation rolls the whole
operation back. External effects, ledger posting and workflow scheduling require
separate qualified transaction/fencing contracts.

PostgreSQL 16 transaction semantics rechecked on 7 November 2026 against
[transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html).

## Attempt budgets and recorded failures

Migration 0054 adds creation-time `max_attempts`, default 3 and configurable from
1 to 20. Creation-key replay requires the same payload and limit. Each successful
claim increments `attempts_started`, including expired-lease recovery. An exhausted
expired running job becomes terminal `failed` when the next claim is attempted.
That terminal transition commits even though the claim returns ValueError.

For existing jobs, migration starts a fresh counted budget at `budget_started_at`.
Earlier claim totals were never recorded. Existing state, progress and live leases
are preserved, and only claims acquired after this migration consume the new count.
A worker already running at migration can finish or record its outcome normally.

Call `fail(actor, tenant, job_id, token, failure_code, retryable=...,
retry_after_seconds=60)` with the live worker claim. Supported codes are
`temporary_dependency`, `invalid_input`, `source_unavailable` and `unexpected_error`.
The worker explicitly classifies retryability. The delay is 0–86,400 seconds.
Keep exception messages, credentials and document content outside these receipts.

Failure releases the lease and either queues a delayed retry within the remaining
budget or records terminal failure. State and immutable `JobFailureReceipt` commit
together under the job lock. The receipt records worker, code, retry outcome and
time. Identical worker/token/input replay returns the historical receipt, including
after a newer claim starts, while preserving that newer claim. Changed outcomes
under the same attempt token conflict. Cancelled, completed, expired or superseded
claims reject new failure records. Completed and failed jobs retain terminal state.

`get` retains its existing response shape. `retry_state` requires records read and
returns the limit, counted attempts, budget start, eligible retry time, last failure
code and terminal failure time. `lease_exhausted` is the reserved automatic code for
exhausted lease recovery. Cancellation of a delayed queued retry clears its retry
time and preserves failure history and attempt count.

Add SELECT, INSERT on `omnixat.agent_job_failures` to the job-role grants for failure
recording. Other job methods continue to use their existing table grants. Apply all
migrations before using this adapter version. The SQL boundary retains its existing
application trust requirements. Job scheduling and provider operations still need
separate qualification.

Lock and database-clock semantics rechecked on 7 November 2026 against PostgreSQL 16
[explicit locking](https://www.postgresql.org/docs/16/explicit-locking.html) and
[time functions](https://www.postgresql.org/docs/16/functions-datetime.html).

## Recoverable evidence task specifications

Migration 0055 adds `EvidencePreparationTask` in `omnixat_core.job_tasks` and
`create_evidence_task(actor, tenant, request_key, task, max_attempts=3)` on the
PostgreSQL store. Construct the frozen task using organisation/evidence UUIDs and
32 fingerprint bytes. Its only supported kind/version is `prepare_evidence`/1.
No free text, document bytes, prompts, URLs or credentials are task inputs.

Creation requires records read and write permissions, including matching API
scopes. The registered evidence must match the exact tenant, organisation, ID and
SHA-256. Composite foreign keys maintain that binding. The job and specification
commit or roll back together. The existing creation-key digest and attempt-limit
checks cover the canonical typed payload. Identical concurrent retries return the
original job and creator; changed references or attempt limits conflict.

`get_evidence_task(actor, tenant, job_id)` requires records read and returns the
frozen specification after reconnect, reclaim or a terminal transition. It returns
references only, without evidence availability or processing-success claims.
Document execution must still use the current-policy scan/read gate, resolve fresh
membership/revocation and acquire a live worker lease. Merely recovering a task
cannot authorise processing or a domain effect. No worker starts automatically.

Add SELECT on `omnixat.evidence_registrations` and SELECT, INSERT on
`omnixat.agent_job_evidence_tasks` to the existing job role. Do not grant UPDATE or
DELETE on task specifications. All participating tables require active forced RLS
and a safe non-owner runtime. The existing application SQL trust boundary remains.
References retain their evidence registration; evidence deletion/retention must
account for dependent tasks rather than silently cascading their history away.

Legacy `create` remains hash-only and has no recoverable specification. Migration
preserves such jobs and does not invent inputs. Even a legacy hash matching the
new canonical payload cannot be retrofitted by replaying typed creation; use a new
request key for a new task. This slice does not wire tasks to providers, note
execution, posting, scheduling or approval. The next increment should connect a
bounded executor to fresh identity, lease and evidence-read checks.

Composite-reference and retry semantics rechecked on 7 November 2026 against
PostgreSQL 16 [constraints](https://www.postgresql.org/docs/16/ddl-constraints.html)
and [INSERT](https://www.postgresql.org/docs/16/sql-insert.html).
