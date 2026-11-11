# Customer expense journal preparation

An eligible persisted expense and its recorded funding can now be inspected,
previewed with an explicit configured counterpart, and saved as a balanced journal
**draft** from the customer website and shared API. This records no journal review
decision, posting, correction, statutory approval or submission. Internal interactive
approval guards remain unchanged; bearer scopes are never removed or upgraded.

## Separate optional capabilities

Apply migrations through 0076. Supply three separate non-owner, non-superuser,
non-BYPASSRLS logins, with only schema USAGE and the corresponding EXECUTE grant:

```sql
GRANT USAGE ON SCHEMA omnixat_customer_journals TO journal_reader, journal_previewer, journal_writer;
GRANT EXECUTE ON FUNCTION omnixat_customer_journals.inspect(text,text,bigint,uuid,uuid,uuid) TO journal_reader;
GRANT EXECUTE ON FUNCTION omnixat_customer_journals.preview(text,text,bigint,uuid,uuid,uuid,uuid,uuid) TO journal_previewer;
GRANT EXECUTE ON FUNCTION omnixat_customer_journals.create_draft(text,text,bigint,uuid,uuid,uuid,uuid,uuid,bytea) TO journal_writer;
```

Do not grant the private `_preview` helper, mixed journal capabilities, direct
omnixat/extraction schema access, schema CREATE, identity/policy administration or
approval rights to application roles. The service rejects mixed journal grants.
A separate function owner must have the underlying SELECT/lock/INSERT privileges
and existing tenant RLS policies; see the non-BYPASSRLS integration qualification.

Private mode-0600 DSN files are read from
`OMNIXAT_EXPENSE_JOURNAL_READ_DSN_FILE`,
`OMNIXAT_EXPENSE_JOURNAL_PREVIEW_DSN_FILE`, and
`OMNIXAT_EXPENSE_JOURNAL_WRITE_DSN_FILE`. Explicit construction uses matching
`expense_journal_{read,preview,write}_connection_factory` parameters, under the
configured server's existing 16-lease bound. Enable evidence/spool and saved expense
inspection for the website. No server, grants or live configuration are activated
by this change. Routes are absent without the corresponding capability.

Configured counterpart accounts must match the recorded funding source, be enabled
and differ from the expense account. Account references are opaque; account labels,
operator settings management and accounting/tax classification remain unfinished.
No default account or customer-entered amount is accepted.

## Shared API

Base path:
`/v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/expense-drafts/{draft}/journal`.

- GET: verified `records:read` and `evidence:read`, fresh persisted human membership.
  Returns eligible saved `journal` or null, `saved_unavailable`, first 20 configured
  `choices` with `account_id`, and `has_more`. Viewer memberships or read-only bearer
  scopes receive no choices. A retained but ineligible journal is explicitly marked
  unavailable and never represented as permission to create a replacement.
- POST to the base path plus `-preview`: add `records:write`, current human
  editor/owner and exact `X-OmniXat-Expected-Actor`. Exact JSON:
  `{ "counterpart_account_id": "<canonical nonzero UUID>" }`. Returns a balanced
  debit/credit preview and `preview_sha256`; persists nothing.
- POST to the base path: same authority, exact JSON with `counterpart_account_id`
  and lowercase 64-character `preview_sha256`. Returns 201 and a stable draft
  receipt. The shared writer locks current source, scan, funding, accounting and
  identity gates; the digest is checked again under those locks. A changed preview
  returns 409 `journal_preview_changed` and rolls back the entire transaction.
  Exact actor/input retries return the same receipt; conflicting saved inputs return
  409 `journal_conflict`. No blind retry changes the saved journal.

All paths bind tenant, organisation, evidence and draft. The strict shared transport
rejects queries/idempotency headers, duplicate/extra JSON keys, media encodings,
nonfinite values and bodies over 2048 bytes/five seconds. Amount and pence values
are serialized as exact strings; the browser performs no financial calculation.
Provenance includes evidence/job/source cell, scan policy and evidence fingerprint.
Saved attribution/time and the separate saved-review snapshot fingerprint are shown.
A preview digest is not a review decision or an approval signature.

The browser requires explicit selection, displays both lines before enabling save,
and invalidates a preview when the account changes. An uncertain save retains the
same preview, payload and initiating actor in the current tab. Expiry clears visible
source details; sign-in recovery can retry that same attempt. Account switches cannot
reattribute it. Reload/tab closure loses local pending state: inspect retained saved
records before preparing replacements. Empty eligible reads do not prove no commit.

## Qualification and next step

`test_customer_expense_journals.py` exercises real PostgreSQL boundaries, shared
readers/writers, source/account binding, stale preview rollback, concurrent receipts,
separate grants, current scopes/membership and non-BYPASSRLS function ownership.
`test_customer_expense_journals_ui.py` requires real Chromium and covers explicit
preview/save/inspection/mobile, committed lost receipts/account switching, and expiry
recovery. Existing fictional-demo browser approval remains mandatory.

Next: connect historical journal review observations and correction journeys with
separate narrow grants and exact snapshot binding. Neither is statutory approval.
Production qualification, operator chart configuration, full accounting coverage,
posting, billing and qualified statutory/banking adapters remain outstanding.

PostgreSQL 16 SECURITY DEFINER/search-path/PUBLIC EXECUTE and transaction lock
semantics were rechecked on 11 November 2026 against official documentation:
https://www.postgresql.org/docs/16/sql-createfunction.html and
https://www.postgresql.org/docs/16/explicit-locking.html. No legal rule or dependency
version was changed in this increment.
