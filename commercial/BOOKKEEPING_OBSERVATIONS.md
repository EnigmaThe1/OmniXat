# Explicit customer bookkeeping observations

Human owners/editors can record an explicit `reviewed` or `changes_requested`
historical bookkeeping observation for the exact saved journal snapshot displayed.
This does not approve accounts or filings, correct amounts, post a journal, submit
documents, or unlock another workflow. Internal interactive-only review/approval
services retain their guards; no bearer scopes are removed or upgraded.

## Separate optional capability

Apply migrations through 0078. Use a separate non-owner, non-superuser,
non-BYPASSRLS login with only:

```sql
GRANT USAGE ON SCHEMA omnixat_customer_journal_decisions TO bookkeeping_writer;
GRANT EXECUTE ON FUNCTION omnixat_customer_journal_decisions.record_observation(text,text,bigint,uuid,uuid,uuid,uuid,bytea,text) TO bookkeeping_writer;
```

Do not mix this writer with journal read/preview/save or observation-reader grants,
direct omnixat/extraction schema access, schema CREATE, identity/policy management
or statutory approval rights. Reader and writer services reject mixed capabilities.
The separately managed definer needs the underlying SELECT/lock privileges and
INSERT on expense_journal_review_decisions under existing tenant RLS; the integration
suite qualifies the complete chain without BYPASSRLS. No RLS policy/table is relaxed.

Configure private mode-0600 `OMNIXAT_BOOKKEEPING_OBSERVATION_DSN_FILE`, or pass
`bookkeeping_observation_connection_factory` explicitly. The configured server shares
its existing 16-lease bound. The website also requires evidence/spool, saved expense,
saved journal and observation-history readers. Routes are absent without the specific
capability; a reader-only installation continues to reject POST. No server, grants or
live configuration is activated automatically.

## Shared API and immutable receipts

POST `/v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/expense-drafts/{draft}/journal-observations`
requires verified `records:read`, `records:write`, `evidence:read`, a fresh persisted
human owner/editor, and `X-OmniXat-Expected-Actor` matching the initiating user. A
viewer, revoked/disabled identity, stale token, agent identity or switched actor is
rejected. Token role/actor claims cannot replace persisted membership. Supported
human bearer access records only a bookkeeping observation, never statutory approval.

Exact JSON: `{"snapshot_sha256":"<lowercase saved snapshot digest>","decision":"reviewed"}`
or `changes_requested`. No actor, amount, approval flag/date, correction reason or
posting field is accepted. Existing strict JSON transport enforces 2048 bytes/five
seconds, duplicate/extra-key rejection, exact media type and no query/idempotency
parameters. The successful 200 receipt includes journal_id, snapshot_sha256, decision,
reviewer_id and recorded_at, all scoped to the selected saved journal.

The SQL boundary independently binds tenant, organisation, evidence, expense draft and
saved journal. Identity/membership, active policy, accounting context, saved journal,
funding mapping/source, quarantine/registration, scan claims and amount/extraction
records are locked in the shared journal writer's order through commit. The existing
validated saved-snapshot reader and decision store are reused under those locks.
A changed fingerprint returns 409 `journal_snapshot_changed`; an unavailable source
or context returns 404, without recording an observation. Different existing choice
for the same reviewer/snapshot returns 409 `bookkeeping_observation_conflict`.

Same actor, snapshot and choice retries return the original receipt/time; concurrent
same-attempt retries produce one observation. Each reviewer has a separate immutable
observation per saved snapshot. Retained history is not overwritten or treated as a
current correction. Changing source eligibility after a confirmed observation does
not erase it, and may prevent current inspection/retry. Reconcile retained records
before replacing an uncertain attempt. These are bounded observation effects, not
production exactly-once ledger guarantees.

## Customer journey and limits

Saved journal inspection displays exact lines, provenance and saved fingerprint.
The new form has no default: choose Reviewed or Changes requested explicitly. Its
labels distinguish bookkeeping observation from correction/posting/statutory approval.
On a confirmed receipt it shows attribution/time and refreshes current-snapshot
history. Viewer membership hides the form while retaining authorised read access.

An uncertain save keeps its exact payload/snapshot/actor in the current tab and locks
selection. Expiry clears source panels; refreshed sign-in can recover and retry the
same attempt. Switching accounts cannot reattribute it. Known rejection disables that
attempt and requires fresh journal inspection. Pending state is not persisted across
reload/tab closure. No model or background agent decides the human's observation.
No correction reasons, focused follow-up answers, amount replacement or final package
approval are connected yet. Account labels/settings and complete accounting remain open.

Qualification: seven real PostgreSQL cases cover stable/concurrent receipts,
snapshot/source/tenant binding, role/scopes/identity, mixed grants/context cleanup,
non-BYPASSRLS ownership and lock retention. Four real Chromium cases cover explicit
choice/mobile/viewer/conflict, committed lost receipt/account switching, pending-save
expiry recovery, and changed-snapshot fresh inspection. Existing retained fictional
browser approval remains mandatory. No tests are removed or skipped to claim green.

Next: focused correction reasons/questions and retained correction inspection, then
supported correction execution. These remain separate from human approval of an exact
final statutory package. Production security/restore/provider qualification, OCR/model
workflows, posting, billing and qualified bank/statutory adapters remain unfinished.

No dependencies or legal rules changed. PostgreSQL 16 SECURITY DEFINER and row-lock
semantics were rechecked on 11 November 2026 using official
https://www.postgresql.org/docs/16/sql-createfunction.html and
https://www.postgresql.org/docs/16/explicit-locking.html.
