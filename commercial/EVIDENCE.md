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

## GBP expense draft preflight

Migration 0024 stores internal accounting periods and expense-account
eligibility under the exact tenant and organisation. An operator must
explicitly open a period and enable an account for drafting; both flags
default to false. No period or account is selected automatically. These
records are preparation policy, not a chart of accounts or a statutory
or tax calendar. There is no policy administration endpoint.

`prepare_csv_expense_draft` takes an explicit period UUID, GBP currency,
accounting date and account UUID. It requires an interactive tenant editor
or owner with evidence access. The date must be within the selected
period (including both boundary dates). A single read snapshot checks
that the period and account are eligible and that the exact draft amount
still passes the active scanner policy. The preview preserves the source
and period ID and accepts only positive whole-penny amounts without rounding.

Provision a separate non-owner, NOBYPASSRLS preview login with USAGE on
`omnixat_extraction` and EXECUTE only on
`omnixat_extraction.read_csv_expense_preview(uuid,uuid,uuid,text,integer,integer,uuid,uuid,date)`.
Do not grant table access or combine this login with the draft amount
reader, writer, or scanner. Provision policy rows through a trusted
operator connection, using the transaction-local `omnixat.tenant_id`
context for a non-bypass role. Keep policy writes off the preview login.

For currency reference see the [ISO 4217 maintenance agency](https://www.six-group.com/en/products-services/financial-information/market-reference-data/data-standards.html).

The preview has no durable effect and may become stale after it returns.
Use the separate write service below to save a draft.

## Transactional GBP expense drafts

Migration 0025 adds `create_csv_expense_draft` for interactive tenant
owners and editors with evidence access. PostgreSQL derives pence from
the exact eligible CSV draft amount, checks the selected period and
account, and rejects zero, negative amounts and fractional pence. The
caller supplies no money value and the saved draft links to the exact
source amount. The active scanner policy, period and account rows stay
locked through commit. The quarantine and claim locks prevent changes
to current scan eligibility during the write.

There is one draft per tenant, extraction job and amount field.
Identical retries return the original ID, pence and timestamp while
the source and context remain eligible. A different actor or accounting
context conflicts for the same eligible source. This does not deduplicate
separate extraction jobs or determine whether two documents describe
the same expense. A transient database lock failure can be retried with
the identical request.

Give a separate non-owner, NOBYPASSRLS writer login USAGE on
`omnixat_extraction` and EXECUTE only on
`omnixat_extraction.create_csv_expense_draft(uuid,uuid,uuid,text,integer,integer,uuid,uuid,date,text,text)`.
Do not grant direct table access or combine it with preview, scan or
extraction roles. The draft does not set VAT, payer or tax treatment,
create a journal, or approve or submit any filing.

## Scoped expense draft review

Migration 0026 adds `read_csv_expense_draft` for interactive tenant
users with records and evidence read permissions, including viewers.
Supply the organisation ID and saved expense receipt ID. One snapshot
checks scanner eligibility, the saved period and account, and the match
between the stored pence and the exact source amount. Missing, out-of-scope
and currently ineligible drafts all return the same unavailable result.

The result contains the saved accounting context and expense attribution,
along with the exact source decimal, evidence fingerprint, extraction
job and cell, source kind, and draft amount attribution. It does not
return the original file bytes or clarification text. A review is
read-only and does not certify continued eligibility after it returns.

Give a separate non-owner, NOBYPASSRLS reader USAGE on
`omnixat_extraction` and EXECUTE only on
`omnixat_extraction.read_csv_expense_draft(uuid,uuid)`.
Keep direct table access and preview, writer or scanner grants separate.

## Explicit payer and funding context

Migration 0027 adds operator-provisioned funding source records scoped to
a tenant and organisation. A source has an opaque payer UUID and a
`business_funds` or `personal_funds` classification. Sources default to
disabled. These identifiers do not verify a person's identity or a bank
payment; no bank details are collected. Retire a source by disabling it
and provision a new one if its payer or kind changes.

`record_expense_funding_context` requires an interactive tenant editor
or owner with evidence access to select both UUIDs for a saved expense
draft. The service checks current expense eligibility and locks the
selected funding row through commit. Identical eligible retries return
the original timestamp; a changed eligible choice or actor conflicts.
This records one selection and provides no correction or review endpoint.
Draft eligibility is checked at write time; any later journal preparation
must check it again and validate an explicit counterpart account.

Give a dedicated non-owner, NOBYPASSRLS writer USAGE on
`omnixat_extraction` and EXECUTE only on
`omnixat_extraction.record_expense_funding_context(uuid,uuid,uuid,uuid,text)`.
Do not grant direct table access or combine this with other evidence roles.
A funding choice does not infer reimbursement, a director's loan, tax
treatment or a ledger account, and it cannot move funds or post a journal.

## Scoped funding review

Migration 0028 adds `read_expense_funding_context` for interactive tenant
users with records and evidence read permissions, including viewers.
Supply the organisation and expense receipt IDs. The read rechecks
expense eligibility and funding source status in one snapshot. It returns
the saved payer reference, funding source and kind, recorder and timestamp,
plus whether the recorded source is still eligible. A disabled source
remains visible as historical context and must not be used for preparation.

An eligible draft with no funding choice returns `None`. Missing,
out-of-scope and ineligible expense drafts return the same unavailable
result. The read does not verify payment or select a counterpart account.

Give a dedicated non-owner, NOBYPASSRLS reader USAGE on
`omnixat_extraction` and EXECUTE only on
`omnixat_extraction.read_expense_funding_context(uuid,uuid)`.
Keep it separate from writer and other evidence grants.

## Counterpart policy and journal preview

Migration 0029 adds an operator-managed allowlist of counterpart account
UUIDs per tenant, organisation and funding source. Each entry defaults to
disabled. It is a preparation policy, not a chart of accounts or a default
mapping; the operator must validate account suitability before enabling it.

`prepare_expense_journal_preview` requires an interactive tenant owner or
editor with evidence access and an explicitly selected counterpart account.
A single read rechecks the saved expense and its evidence, period, expense
account, recorded funding source and counterpart policy. The counterpart
must differ from the expense account. The preview uses the saved exact GBP
pence for both lines, debiting the expense account and crediting the
selected counterpart, and includes the draft, funding and evidence links.
It is limited to a single amount and two lines. It neither verifies a
payment nor decides reimbursement, account classification or tax treatment.

Give a dedicated non-owner, NOBYPASSRLS preview login USAGE on
`omnixat_extraction` and EXECUTE only on
`omnixat_extraction.read_expense_journal_preview(uuid,uuid,uuid)`.
Keep direct table access and other evidence grants separate. This preview
is not durable; a future journal draft writer must recheck all inputs
inside its transaction. It cannot post or approve anything.

## Saving a balanced journal draft

Migration 0030 adds `create_expense_journal_draft`. An interactive tenant
owner or editor with evidence access selects the counterpart account for
a saved expense. PostgreSQL reuses the preview checks after locking the
scanner policy, relevant evidence, period, expense account, funding and
counterpart rows. The locks remain until commit. A retryable lock conflict
can be retried with the same inputs.

The draft stores one exact positive GBP pence amount for two distinct
accounts, plus the expense link, funding source, date, period, scanner
policy, evidence fingerprint and attribution. Identical eligible retries
return the original receipt; a different eligible selection or actor
conflicts. A later policy change can make a saved draft ineligible without
deleting it. No ledger balances change.

Give a separate non-owner, NOBYPASSRLS writer USAGE on
`omnixat_extraction` and EXECUTE only on
`omnixat_extraction.create_expense_journal_draft(uuid,uuid,uuid,text)`.
Keep direct table access and preview grants separate. There is no
journal review endpoint, posting, payment or approval in this slice.

## Reviewing a saved journal draft

Migration 0031 adds `read_expense_journal_draft` for interactive tenant
users with records and evidence read permissions, including viewers.
Supply the organisation and journal receipt IDs. In one snapshot the
service reruns the preview eligibility checks and compares the saved
accounts, funding, amount, currency, date, period, scan policy and
fingerprint to current inputs. Missing, out-of-scope, stale and mismatched
drafts all return the same unavailable result.

An eligible review returns the original receipt and attribution, both
saved journal lines, and provenance from the linked expense: evidence ID,
extraction job and CSV cell. The read does not expose original bytes or
perform any mutation, approval or posting. Current eligibility can change
after the review returns.

Give a separate non-owner, NOBYPASSRLS reader USAGE on
`omnixat_extraction` and EXECUTE only on
`omnixat_extraction.read_expense_journal_review(uuid,uuid)`.
When upgrading from migration 0031, replace the old
`read_expense_journal_draft(uuid,uuid)` grant for that reader; migration
0032 leaves existing ACLs unchanged. Keep direct table access and preview
or writer grants separate.

## Recording a human journal review decision

Migration 0032 includes a versioned SHA-256 snapshot digest in eligible
journal reviews. The digest binds the scope, saved journal, exact amount
and accounts, funding reference, period, attribution and evidence
provenance. An interactive tenant owner or editor with evidence access
can record `reviewed` or `changes_requested` against the exact digest
they saw. PostgreSQL recomputes it against the currently eligible journal
at the write boundary. An identical eligible retry returns the original
receipt; a changed decision for the same reviewer and snapshot conflicts.
Different reviewers can leave distinct observations.

A decision is a historical bookkeeping observation. It is not a
commit-time eligibility lock, current readiness signal, payment, posting
instruction or statutory approval. No aggregate verdict or correction
workflow is defined. Any downstream action must independently verify
current eligibility and authority.

Give a dedicated non-owner, NOBYPASSRLS decision writer USAGE on
`omnixat_extraction` and EXECUTE only on
`omnixat_extraction.record_expense_journal_decision(uuid,uuid,bytea,text,text)`.
Keep it separate from journal reader and writer roles.

## Reading journal review decisions

Migration 0033 adds `read_expense_journal_decisions` for interactive tenant
users with records and evidence read permissions, including viewers.
Supply the organisation, journal receipt and exact digest returned by
journal review. In one snapshot, the read rechecks current eligibility
and returns only matching observations with reviewer and timestamp.
A matching snapshot can have an empty page; stale, missing and
out-of-scope snapshots return the same unavailable result.

Pages contain 1–100 requested entries at most (default 25), in reviewer
ID order. To continue, reuse the same digest and pass the returned
`next_after_reviewer` as `after_reviewer`. Each page is a fresh read;
restart from the first page to include newly recorded reviewers who
sort before the cursor. Older snapshots are retained but not listed here.
The list conveys no overall verdict, approval or posting authority.

Migration 0035 adds correction receipts to the same read snapshot.
The page's `corrections` tuple contains only reasons and timestamps for
decisions on that page. Match a correction to its decision by reviewer
ID within the page. A changes-requested decision can exist without a
reason; a reason from a different snapshot is never carried forward.
Decision receipts, page size and cursor behavior are unchanged.

`page.follow_up_questions` returns a fixed question for each distinct
unanswered correction reason on the page, in order of first appearance. Each item
contains a reason and question text. Callers collecting multiple pages
can deduplicate by reason for the same snapshot. This derived property
uses no record values or reviewer identifiers in the question text and
has no database writes or delivery side effects.

Give a dedicated non-owner, NOBYPASSRLS reader USAGE on
`omnixat_extraction` and EXECUTE only on
`omnixat_extraction.read_expense_journal_decisions_with_evidence(uuid,uuid,bytea,text,integer)`.
When upgrading, revoke the reader's previous EXECUTE grant on the decision
reader from migration 0033, 0035 or 0037. Migration 0039 leaves existing
ACLs unchanged. Keep direct table access and
other journal grants separate.

Migration 0037 adds `page.answers`. Each entry includes the answer text and
its original receipt, with the author, recording time and correction reviewer.
Answers are unique by reason within a page and are returned only for reasons
visible on that page. The same answer applies to every correction for the
same reason on that snapshot, even across different pages. Answer text is
private tenant data and is excluded from the default object representation.

## Recording a structured journal correction request

Migration 0034 lets an interactive tenant owner or editor with evidence
access attach one correction reason to their own `changes_requested`
observation for the currently eligible journal snapshot. The supported
reasons are `amount`, `account`, `funding`, `accounting_date` and
`source_evidence`. There is no free-text input. The reviewer identity
comes from the trusted principal, and a scoped foreign key requires
the matching changes-requested observation.

An identical eligible retry returns the original receipt. A different
reason conflicts; missing, stale and out-of-scope targets are unavailable.
The record neither changes the journal nor replaces the decision. No
resolution workflow, approval or posting is enabled.

Give a dedicated non-owner, NOBYPASSRLS writer USAGE on
`omnixat_extraction` and EXECUTE only on
`omnixat_extraction.record_expense_journal_correction(uuid,uuid,bytea,text,text)`.
Keep direct table access and other journal grants separate.

## Recording a journal clarification answer

Migration 0036 adds `record_expense_journal_clarification`. An interactive
tenant owner or editor with evidence read and records write permission can
answer a question on the exact eligible journal snapshot. Pass the reason
and the reviewer ID of a correction request carrying that reason. The
answer is a single line of up to 1,000 printable characters and is stored
with the authenticated author and timestamp.

Each snapshot and reason accepts one answer, even if several reviewers
requested the same correction. An identical retry by the original author
returns the original receipt and correction reference. A different author
or answer conflicts. Eligibility is checked on write and replay. The write
holds the active scan policy through commit. Answer text is private tenant
data and is absent from the write receipt.

Grant the dedicated writer USAGE on `omnixat_extraction` and EXECUTE on
`omnixat_extraction.record_expense_journal_clarification(uuid,uuid,bytea,text,text,text,text)`
only. The answer does not alter the journal, the correction request or
the review decision, and carries no approval or posting authority.

## Linking supporting evidence to a journal clarification

Migration 0038 adds `link_expense_journal_clarification_evidence`. An
interactive tenant owner or editor with records write and evidence read
permission can link one supporting original per answered reason on the
eligible journal snapshot. The evidence must belong to the same tenant
and organisation and pass the active scan policy. The receipt records the
exact fingerprint, scan policy, author and time. The active policy and
supporting evidence scan state are held through the write.

An eligible retry with the same evidence and author returns the original
receipt. A different eligible link conflicts. The link is an attributed
reference for review. Bookkeeping treatment remains a separate decision.

Grant the dedicated writer USAGE on `omnixat_extraction` and EXECUTE on
`omnixat_extraction.link_expense_journal_clarification_evidence(uuid,uuid,bytea,text,uuid,text)`
only. The write receipt carries no original bytes or answer text.

Migration 0039 adds `supporting_evidence` to each answer in the scoped
decision page. An answer with a link shows the original receipt and a
boolean indicating whether the linked fingerprint is currently admitted
by the scan gate. This distinguishes a link that has become ineligible
from an answer with no link. The page returns metadata only for the exact
snapshot and visible reasons. Access to original bytes remains separate.

Migration 0040 keeps decision, correction and answer writes retry-safe
when concurrent inserts collide on either index for the same record.
Existing receipts, scoped foreign keys and grants are preserved.

## Previewing a journal amount correction

Migration 0041 adds `preview_expense_journal_amount_correction`. An
interactive tenant owner or editor with records write and evidence read
permission selects the extraction job and exact CSV field, row and
column, and explicitly confirms GBP. The cell must contain a unique
extracted amount from the document linked to the answered amount
correction on the exact eligible journal snapshot. The scan gate
rechecks the current fingerprint and policy. Clarification text is
separate from the source amount.

The service requires a positive amount expressible in whole pence.
It returns the previous amount and two equal proposed amounts for the
existing debit and credit accounts, with the evidence and cell provenance.
The operation is read-only.

Grant the dedicated preview reader USAGE on `omnixat_extraction` and
EXECUTE on
`omnixat_extraction.read_expense_journal_amount_correction(uuid,uuid,bytea,uuid,text,integer,integer)`
only. Original bytes and other journal grants remain separate.

## Saving a journal amount-correction proposal

Migration 0042 adds `create_expense_journal_amount_correction`. An
interactive tenant owner or editor selects the same exact extraction
cell as the preview and explicitly confirms GBP. PostgreSQL derives
the proposed amount, requires positive whole pence and stores the
original snapshot, both account IDs, evidence fingerprint, extraction
coordinates and authenticated author.

One proposal is retained per journal snapshot. An identical eligible
retry by the original author returns its receipt. A different source
selection or author conflicts. The writer protects journal policies,
both originals, scanner state and the relevant extraction records
through commit. The original journal and clarification are retained.

Grant the dedicated writer USAGE on `omnixat_extraction` and EXECUTE on
`omnixat_extraction.create_expense_journal_amount_correction(uuid,uuid,bytea,uuid,text,integer,integer,text,text)`
only. The receipt contains an ID, journal snapshot and creation time.
A proposal is preparation for a separate review and replacement action.

## Reviewing a saved amount-correction proposal

Migration 0043 adds `read_expense_journal_amount_correction`. An interactive
tenant reader with records read and evidence read permission selects a
proposal receipt ID in its organisation. The read checks the saved journal
snapshot, linked evidence fingerprint and scan policy, selected extraction
cell, original and proposed pence, and both account IDs on one statement
snapshot. Stale or changed proposals are unavailable.

The result contains the original receipt, author and the same balanced GBP
proposal and provenance returned by the preview. Access is read-only.
Grant a dedicated reader USAGE on `omnixat_extraction` and EXECUTE only on
`omnixat_extraction.read_expense_journal_amount_correction_review(uuid,uuid)`.
When upgrading from migration 0043, replace the previous reader grant on
`read_saved_expense_journal_amount_correction(uuid,uuid)`. Migration 0044
preserves existing ACLs. Original bytes, write functions and direct table
access remain separate.


## Recording an exact-proposal review decision

Migration 0044 adds `proposal_sha256` to the saved proposal review. The
versioned digest binds tenant, organisation, proposal identity, author,
creation time, original journal snapshot, evidence, cell and balanced
amounts/accounts. Its timestamp representation is independent of session
timezone.

An interactive owner or editor with evidence access can record `reviewed`
or `changes_requested` against that digest. Each reviewer has one decision
per exact proposal. Identical eligible retries return the original receipt,
and a different decision conflicts. Historical decisions remain attributed
to their original digest. These are bookkeeping observations. Journal
replacement, ledger posting and statutory approval remain separate actions.

Grant the dedicated decision writer USAGE on `omnixat_extraction` and
EXECUTE only on
`omnixat_extraction.record_expense_journal_amount_correction_decision(uuid,uuid,bytea,text,text)`.

## Reading proposal review decisions

Migration 0045 adds `read_expense_journal_amount_correction_decisions`.
An interactive tenant reader with records read and evidence read permission
can read observations for the exact eligible proposal digest. Each page
contains up to 100 decisions (default 25) in reviewer-ID order. Continue
with the same digest and the returned `next_after_reviewer` cursor.

An eligible empty page is distinct from an unavailable proposal. Older
digests remain historical records and are excluded. Each page rechecks
eligibility. Restart at the first page to include new reviewers sorting
before the current cursor. A list of observations provides no aggregate
verdict or authority to replace a journal or post ledger entries.

Grant the dedicated history reader USAGE on `omnixat_extraction` and EXECUTE
only on
`omnixat_extraction.read_expense_journal_amount_correction_decisions(uuid,uuid,bytea,text,integer)`.
Keep original-document, proposal-detail and write grants separate.

## Previewing a reviewed replacement draft

Migration 0046 adds `preview_expense_journal_replacement`. An interactive
tenant owner or editor with records write and evidence read permission
selects the exact proposal digest and a reviewer whose observation is
`reviewed` for that digest. Eligibility of the proposal, journal and
linked extraction is rechecked on one statement snapshot.

The result includes the attributed proposal and its balanced GBP amounts,
the selected review observation and the original journal's accounting date,
period and funding source. The selection identifies one observation.
Decision history remains available separately for broader review.

Grant the dedicated preview reader USAGE on `omnixat_extraction` and
EXECUTE only on
`omnixat_extraction.read_expense_journal_replacement_preview(uuid,uuid,bytea,text)`.
The preview is read-only. Saving a replacement draft and posting ledger
entries require their own operations.

## Saving a linked replacement draft

Migration 0047 adds `create_expense_journal_replacement`. An interactive
tenant owner or editor with records write and evidence read permission
selects the exact proposal digest and its reviewed observation. The writer
locks the existing proposal and replays its original inputs through the
transactional proposal writer to revalidate the source and retain its
eligibility locks. It also holds the selected observation through commit.

One replacement draft is stored per original journal. The draft snapshots
the selected review, accounting context, balanced pence amount and exact
evidence provenance with the authenticated draft author. Scoped foreign
keys require the original journal and reviewed observation. Identical
eligible retries return the first receipt. Different authors or selected
observations conflict.

Grant the dedicated writer USAGE on `omnixat_extraction` and EXECUTE only on
`omnixat_extraction.create_expense_journal_replacement(uuid,uuid,bytea,text,text)`.
The original journal and correction proposal are retained as evidence of the
preparation history. Saving this linked draft carries no posting authority.
