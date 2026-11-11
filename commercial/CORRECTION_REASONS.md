# Structured correction reasons and focused inspection

Customers can inspect retained correction requests and record one explicit reason
against their own prior `changes_requested` bookkeeping observation for the exact
saved journal snapshot. This records a request for clarification, not an applied
correction, new observation, changed amount, posted entry, approval or submission.
Internal interactive-only services and final-package approval guards are unchanged.
No bearer scope is stripped or converted to approval authority.

## Separate optional capabilities

Apply migrations through 0079. Separate non-owner, non-superuser, non-BYPASSRLS
application logins need only:

```sql
GRANT USAGE ON SCHEMA omnixat_customer_corrections TO correction_reader, correction_writer;
GRANT EXECUTE ON FUNCTION omnixat_customer_corrections.inspect(text,text,bigint,uuid,uuid,uuid,bytea,text) TO correction_reader;
GRANT EXECUTE ON FUNCTION omnixat_customer_corrections.record_reason(text,text,bigint,uuid,uuid,uuid,uuid,bytea,text) TO correction_writer;
```

Do not mix read/write, journal/observation capabilities, direct omnixat/extraction
schema access, schema CREATE, identity/policy administration or approval rights in
application roles. Services reject mixed capabilities. The separate definer requires
SELECT/lock privileges, correction INSERT and the existing observation/snapshot/
correction function chain. The nested observation retry also requires its ordinary
INSERT privilege, although this path first requires and locks the existing observation
and cannot create one implicitly. The integration suite qualifies the complete chain
without BYPASSRLS. No table or RLS policy is relaxed.

Configure private mode-0600 `OMNIXAT_CORRECTION_READ_DSN_FILE` and
`OMNIXAT_CORRECTION_WRITE_DSN_FILE`, or explicit
`correction_read_connection_factory` / `correction_write_connection_factory`.
The configured server retains the shared 16-lease bound. The website requires
evidence/spool, saved expense and saved journal inspection too. Routes are absent
without their specific capability. No live grants, configuration or server start
is activated by this change.

## Shared API

Base path:
`/v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/expense-drafts/{draft}/journal-corrections`.

GET requires verified records:read/evidence:read, current persisted human membership,
required lowercase 64-character `snapshot_sha256`, and optional `after_reviewer`
(1–200 characters, nonblank, no NUL). It returns journal_id, snapshot_sha256,
verified actor_id, own observation/reason, up to 20 observation/correction items,
has_more/next_after_reviewer, eligible reason choices and deduplicated focused
questions for that page. Own prerequisite is read independently of pagination.
Viewer/read-only tokens receive no choices. Unknown/duplicate query parameters and
invalid snapshots/cursors return 400. A changed eligible snapshot returns 409
journal_snapshot_changed; unavailable current journal/source/context returns 404.
These are never represented as an empty successful history.

Read eligibility, fingerprint, own context and page share one statement snapshot.
Questions use the existing shared journal_correction_questions service. An already
recorded clarification for the same tenant/organisation/journal/snapshot/reason
suppresses its question. The response exposes only a clarification-recorded flag,
not the private answer text or evidence links. Recorded clarification does not prove
that a correction has been applied or its evidence independently validated. Answer
and supporting-evidence inspection/submission remain the next increment.

POST requires records:read/records:write/evidence:read, a current human owner/editor,
X-OmniXat-Expected-Actor, and exact JSON `{snapshot_sha256, reason}`. Supported reasons
are amount, account, funding, accounting_date and source_evidence. No figure, answer,
reviewer, approval or posting field is accepted. The strict shared JSON transport
bounds bodies to 2048 bytes/five seconds and rejects extra/duplicate keys, unsupported
media encodings, query parameters and idempotency headers.

The writer first verifies identity/actor and locks the caller's prior exact-snapshot
changes_requested observation, bound to tenant/organisation/evidence/expense/journal.
Missing prerequisite returns 404 without creating an observation or reason. A reviewed
observation cannot be converted into changes_requested here. It then reuses the strong
observation boundary as an existing same-choice retry, retaining identity, policy,
source/scan, funding, accounting and saved-journal gates through correction commit.
Shared validated correction storage returns the stable 200 receipt (journal_id,
snapshot_sha256, reason, reviewer_id, recorded_at). Exact concurrent retries reuse it;
a different existing reason returns 409 correction_reason_conflict. Ineligible context
returns 404; a changed existing observation snapshot returns 409. Retained records
are not overwritten or deleted. These bounded request effects are not production
exactly-once ledger guarantees.

## Customer journey and limits

Saved journal inspection offers Inspect correction requests. A human with an eligible
own Changes requested observation can choose a reason explicitly; there is no default.
Retained reasons show reviewer/time and focused questions. Duplicate questions across
loaded pages are suppressed. Viewer inspection remains available under read authority.
Pages are live reads, not a frozen manifest: refresh starts from page one and discovers
new earlier reviewer IDs or newly recorded clarifications. Reaching the last page is
not a completeness or approval claim.

Uncertain writes preserve exact reason/snapshot/initiating actor in the current tab
and lock selection. Expiry clears source panels; sign-in recovery retries the same
attempt. Account switching cannot reattribute it. Definite rejection requires fresh
inspection. Reload/tab closure loses pending memory; reconcile retained requests before
replacement. Current source/context eligibility may withhold retained history. Actual
clarification answers, replacement proposals, amount corrections, posting, final-package
approval and statutory/banking adapters remain separate and unfinished.

Seven PostgreSQL cases cover stable/concurrent receipts, no implicit observation,
immutable reasons, pagination/answer-aware question suppression, fresh identity/tenant
binding, strict inputs, separate grants/context cleanup, non-BYPASSRLS ownership and
gate lock retention. Four mandatory Chromium cases cover explicit reason/question/
viewer/mobile, committed lost receipt/account switching, pending expiry recovery,
and conflict guidance/pagination/question deduplication. Retained fictional-demo
browser approval remains mandatory; no tests are removed or skipped to claim green.

No dependency or legal rule changed. PostgreSQL 16 SECURITY DEFINER and row-lock
semantics were rechecked on 11 November 2026 against official
https://www.postgresql.org/docs/16/sql-createfunction.html and
https://www.postgresql.org/docs/16/explicit-locking.html.
