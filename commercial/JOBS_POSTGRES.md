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

## Signed identity boundary for preparation jobs

`omnixat_core.jobs_identity_postgres.AuthenticatedJobStore` accepts an exclusive
idle autocommit identity connection, an exclusive idle autocommit job connection
and the existing server-configured `AccessTokenVerifier`. Each method takes an
access token and tenant UUID string instead of a caller-supplied Principal:

```python
jobs = AuthenticatedJobStore(identity_connection, job_connection, server_verifier)
job = jobs.create_evidence_task(access_token, tenant_uuid, request_key, task)
lease = jobs.claim(access_token, tenant_uuid, job)
inputs = jobs.get_evidence_task(access_token, tenant_uuid, job)
```

The boundary exposes typed task creation, `get`, `get_evidence_task`, `retry_state`,
`claim`, `checkpoint`, `cancel`, `fail` and `create_note_effect`. Parameters and
receipts otherwise follow the trusted job store. It does not expose hash-only
creation or accept customer-selected roles, worker IDs or actor kinds. Pinned
verifier configuration must come from the server. Bearer tokens are arguments for
one call; the boundary stores neither tokens nor resolved principals.

The shared `resolve_record_principal` service verifies the signed access token and
reads persisted identity/membership using a read-only transaction on every call.
Role, human/agent kind, disabled identity, membership revocation and token cutoff
come from the database. Signed scopes are limited to the existing records allowlist.
The job service then checks its existing permissions, live worker/token/lease and
operation-specific retry rules in its own transaction. Notes retain the shared
validated record/audit path. Receipt replay also requires current authority.

Use a separate identity login with only schema USAGE and SELECT on
`omnixat.identities` and `omnixat.memberships`. It needs no job, evidence or note
grants. The job login retains the grants documented above and needs no identity
access. Both must be safe non-owner roles with active RLS. Administrative
provisioning remains separate. Never share either connection concurrently or hold
an outer transaction around a call. The existing records adapter reuses the same
lookup without changing its single-transaction record behaviour.

This is a per-call admission check. Identity lookup and the job operation are
separate transactions: a revocation committed before the next identity lookup is
observed, but it does not cancel a call already admitted, serialize revocation
through effect commit or undo a committed note. Token expiry is checked on entry.
The job lease independently fences stale workers. A bounded executor must still
use the current evidence scan/read gate and recheck authority at later operations;
this boundary neither releases document bytes nor executes a provider or scheduler.
It grants no filing approval, billing or bank access. Entity-specific grants,
maintained-provider provisioning and production qualification remain unfinished.

Transaction visibility rechecked on 7 November 2026 against PostgreSQL 16
[transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html).

## Bounded evidence inspection

`omnixat_core.preparation_postgres.inspect_preparation_evidence(jobs,
gate_connection, access_token, tenant, job_id, lease_token)` explicitly runs one
inspection step. Supply the server's `AuthenticatedJobStore`, an exclusive idle
autocommit execute-only extraction-gate connection, and the current worker lease.
No task scheduler starts on import or construction.

The step obtains the immutable task and current checkpoint together through
`get_claimed_evidence_task`. That method requires records read/write permission,
current running state, matching verified worker/token and an unexpired database
lease. A single read-only statement observes the task and job. Wrong scope,
legacy hash-only jobs and stale claims cannot reach the evidence gate.

It then uses the existing current-policy `read_evidence_for_extraction` service,
including quarantine fingerprint/length validation, clean verdict and live scan
claim checks. The admitted evidence ID and fingerprint must match the pinned task.
Original bytes remain in trusted process memory. The returned `EvidenceInspection`
contains only job/organisation/evidence references, fingerprint, observed policy,
media type and byte count. No document contents, prompts or credentials are saved
in the checkpoint or returned by this step.

The saved checkpoint is `{"step":"evidence_inspected","inspection":{...}}`.
Identity is resolved again before saving; the existing checkpoint transaction
rechecks current worker/token/lease under the job lock. The new optional
`expected_progress` keyword compares the previously observed JSON object with
current saved progress in that same update. A mismatch rolls back without changing
progress, completion or lease. Omit it for the existing unconditional checkpoint
contract. Expected objects follow the existing JSON validity and 65,536-byte bound.
The comparison uses PostgreSQL JSONB equality.

Inspection accepts empty progress or its own inspection stage. It refuses other
stages before reading, and conditional saving preserves a later stage committed
during the read. Retrying after recovery rereads the source through the current
gate and can refresh the observation; it cannot rely on a prior checkpoint as
proof of current eligibility. The job remains running, with the normal 60-second
checkpoint renewal. This is an inspection observation, not extracted figures,
processing completion or continuing permission to use the evidence.

Identity resolution, task read, evidence admission and checkpoint are separate
transactions. Revocation/cancellation/expiry during admission prevents the later
checkpoint when observed by its checks, but cannot retract bytes already read into
the trusted process. A scan-policy change after admission does not rewrite that
historical observation. Every subsequent extraction/effect needs its own current
identity, live-lease and evidence-eligibility checks. Failures propagate to the
caller without completing, cancelling or automatically retrying the job.

No migration or extra grants on the job login are required. Provision a separate
non-owner gate login with only USAGE on `omnixat_extraction` and EXECUTE on
`omnixat_extraction.read_eligible_original(uuid,uuid)`, as in EVIDENCE.md. Do not
grant it direct original-byte table reads or broaden the identity/job logins.
The existing bounded original-size and transaction timeouts apply. This is an
internal preparation step, with no provider, posting, approval or HTTP route.

Checkpoint visibility and database-clock semantics rechecked on 7 November 2026:
PostgreSQL 16 [transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html)
and [time functions](https://www.postgresql.org/docs/16/functions-datetime.html).

## Immutable saved CSV extraction plans

Migration 0056 adds one version-1 `CSVExtractionPlan` per existing evidence task.
Construct it with a tuple of `AmountCell(field_name, row, column)` values and call
`save_csv_plan(access_token, tenant, job_id, lease_token, plan)` on the authenticated
store. The internal store has the corresponding trusted-principal method.

Validation is shared with `read_csv_amounts`: 1–32 selections, unique bounded field
names, one-based logical CSV rows 1–5,000 and columns 1–64. Boolean coordinates,
arbitrary extra fields and unsupported names are rejected. The plan stores only
ordered field/coordinate references. It contains no extracted amounts, document
bytes, prompts, URLs or credentials. Coordinate selection does not establish that
an amount exists or that a particular accounting treatment is correct.

Saving requires current records read/write authority and a live running claim for
that same verified worker. The job row is locked against cancellation, completion
and reclaim. The source must be an exact `text/csv` evidence task. The receipt is
inserted/read and the lease checked again within the same transaction. Identical
concurrent retries return the original plan, creator and database timestamp;
different coordinates, field names or ordering raise `CreationConflict`. Recovery
under a new valid claim can replay the original receipt without changing its author.
Progress and the job lease are not renewed by plan saving.

`get_csv_plan(access_token, tenant, job_id)` requires records read and recovers the
validated, digest-checked `JobCSVPlanReceipt`. Reads remain available for historical
terminal jobs; save/replay requires a current live claim. No plan is backfilled for
legacy jobs, and hash-only jobs cannot acquire a plan without a typed evidence task.
Saved plans are immutable under runtime grants. Create a new job to use a different
plan. Their foreign key retains the task and therefore its exact source binding.

Add SELECT, INSERT on `omnixat.agent_job_csv_plans` to the existing job login.
Do not grant UPDATE or DELETE. Existing identity/task/source grants are unchanged.
The schema forces tenant RLS and enforces one bounded versioned plan per task.
Application validation enforces the full cell schema; reads verify the saved
canonical SHA-256 and refuse invalid/corrupted plans. Raw runtime SQL retains the
existing trusted-application boundary.

A plan is recoverable input, not extraction or evidence admission. Neither save
nor read releases original bytes or runs a provider. A future execution effect must
recheck identity, current worker lease and current-policy evidence eligibility, use
the exact saved plan, and commit its result/receipt under its own fencing contract.
This increment does not wire saved plans to the standalone decimal extraction
service, complete jobs, post ledger entries or approve any package.

Retry and row-lock semantics rechecked on 7 November 2026 against PostgreSQL 16
[INSERT](https://www.postgresql.org/docs/16/sql-insert.html) and
[explicit locking](https://www.postgresql.org/docs/16/explicit-locking.html).

## Saved-plan CSV execution

Migration 0057 adds an immutable tenant-scoped effect receipt linked to both the
saved plan and the existing extraction result. `execute_preparation_csv` recovers
the task and saved plan under fresh signed identity, admits the exact original
through the current scan gate and runs the existing bounded decimal reader.
It returns only a receipt; figures remain in the extraction/review service.
It preserves current progress and leaves the job running for subsequent preparation.

On the **dedicated extraction gate login**, additionally grant:

```sql
GRANT EXECUTE ON FUNCTION omnixat_extraction.store_job_csv_result(uuid,text,uuid,uuid,bytea,text,bytea,jsonb) TO extraction_runtime;
```

No direct table grants or access to the older unfenced `store_csv_result` function
are needed on this job gate login. Keep the migration owner, scanner, identity,
job-data and gate roles separate. Do not expose `store_csv_effect` as an HTTP or
model-facing endpoint: its result input is trusted deterministic worker output.
Like other repository services, database credentials alone do not authenticate
end users; fresh signed identity is established by `AuthenticatedJobStore`.

The function locks the job before checking current worker/token/lease, exact task
fingerprint and ordered plan digest/coordinates. It reuses the existing current
policy/eligibility result writer. Result and first-worker attribution receipt commit
in one transaction; retries retain both originals, including after worker recovery.
Conflicting results, cancellation, missing plans, changed source and lease expiry
roll back new effects. A second database-clock check after insertion catches leases
that expire during the write. This is an admission check before commit, not a
claim that a lease cannot expire in the following commit interval.

Identity, byte admission and effect commit are separate transactions. Membership
revocation is checked again before effect entry; it cannot retract already-read
bytes or stop an already-admitted transaction. Scan eligibility is observed again
by the existing result writer; concurrent scanner changes follow that gate's
snapshot boundary. Retries require current eligibility and a current running lease,
even for an existing receipt. Changed active policies can conflict with a stored
result and require a new reviewed task, rather than silently replacing provenance.
No scheduler, OCR, model, posting, final approval or live integration is enabled.

Technical references rechecked 7 November 2026: PostgreSQL 16
[row locks](https://www.postgresql.org/docs/16/explicit-locking.html) and
[function security](https://www.postgresql.org/docs/16/sql-createfunction.html).

## Metadata-only CSV recovery

Migration 0058 and `AuthenticatedJobStore.get_csv_summary` recover an exact job's
first extraction-effect receipt, source references, current scan-policy version,
counts and pending questions. Use a **separate summary-only login**, with existing
CONNECT permission and only these additional grants:

```sql
GRANT USAGE ON SCHEMA omnixat_extraction TO summary_runtime;
GRANT EXECUTE ON FUNCTION omnixat_extraction.read_job_csv_summary(uuid,text,uuid,bytea) TO summary_runtime;
```

It needs no direct table privileges, original-byte access, full review access or
write function grants. The adapter rejects migration owners and logins with the
existing original/review/extraction/clarification function privileges. Keep the
summary login separate from the extraction gate and human clarification writer.

The signed identity is resolved again after plan recovery. The database read
requires the running job's current worker/token/lease, matching saved-plan digest,
existing effect receipt and source fingerprint. One stable function snapshot
covers job state, current scan eligibility, saved result and human answers.
Candidates are validated against the saved ordered plan before values are removed.
Malformed candidates and answers attached to different coordinates fail closed.
The SQL function itself returns only cell status and answered/unavailable flags;
monetary values, answer authors and document bytes do not leave the database on
this surface. Python rechecks the metadata shape and uses the existing fixed
clarification prompts. No evidence text becomes a question or instruction.

`found_count` counts original decimal candidates; `answered_count` counts human
answers to unresolved cells; `unavailable_count` is the subset explicitly answered
with no amount. Such an answer removes the repeated question but does not make an
amount available. Counts are observations, not posting or completion approval.
No progress, lease, result or answer is changed by recovery. The job remains running.
Cancelled/completed/failed jobs and expired/replaced workers cannot use this read.

This is a snapshot observation, not a lease reservation or ongoing eligibility
promise. Membership changes after identity admission and cancellation/scanner
changes after the statement snapshot cannot retract already-returned metadata.
Later effects still require fresh authority and current eligibility. Human-only
clarification storage and final-package approval boundaries are unchanged.
Next: connect job-linked clarification handoff and expense preparation through the
shared validated services; no scheduler, model or UI starts from this adapter.

Technical references rechecked 7 November 2026: PostgreSQL 16
[function snapshots](https://www.postgresql.org/docs/16/xfunc-volatility.html) and
[security-definer functions](https://www.postgresql.org/docs/16/sql-createfunction.html).

## Saved expense-preparation intent

Migration 0059 adds one immutable `ExpensePreparationPlan` per exact CSV evidence
task. The versioned plan stores only a saved source cell, explicit GBP currency,
accounting date, period ID and expense-account ID. It contains no amount, funding
assumption, tax treatment, user prompt or approval. The existing human expense
preparation boundary and the new plan share the same context-input validator.

Add these grants to the existing **job-data login**:

```sql
GRANT SELECT, INSERT ON omnixat.agent_job_expense_plans TO jobs_runtime;
GRANT SELECT ON omnixat.expense_accounting_periods, omnixat.expense_account_policy TO jobs_runtime;
```

Do not grant UPDATE/DELETE on plans or any policy-write permission. Composite
foreign keys bind the plan to the task's organisation and that organisation's
configured period/account; forced RLS isolates tenants. Existing tasks/plans are
preserved and migration invents no expense inputs.

`AuthenticatedJobStore.save_expense_plan` resolves current identity and both record
scopes. Saving locks the job, requires its current running worker/token/lease,
validates the parent CSV plan/digest and exact selected source cell, and observes
an open configured period, an eligible account and a date within that period.
The first plan and actor persist through restarts/reclaims; changed inputs conflict.
A final database-clock lease check rejects expired writes. Exceptions roll back
the plan. No progress or lease is renewed.

`get_expense_plan` uses current read authority, validates the canonical digest and
returns historical intent even after policy closure or job termination. Reading
or saving this intent does not establish current evidence eligibility or amount
availability. Configuration validation is a statement observation, not a period or
account reservation through commit or later execution. Identity admission and job
work remain separate transactions; revocation governs the next admission. The
final lease check precedes commit, as for saved CSV plans.

No expense, source-amount draft, journal, ledger posting or clarification answer is
created here. Next: a separate job effect must recheck live identity/worker lease,
exact evidence eligibility, current accounting policy and resolved source amount
while atomically creating the shared-service expense result and job retry receipt.
Human-only clarification/approval and UI decisions remain unchanged.

Technical references rechecked 7 November 2026: PostgreSQL 16
[row locking](https://www.postgresql.org/docs/16/explicit-locking.html) and
[conflict handling](https://www.postgresql.org/docs/16/sql-insert.html).
