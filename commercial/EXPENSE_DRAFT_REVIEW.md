# Customer saved expense draft inspection

The optional website/API reader shows persisted CSV expense preparations using the
existing source and accounting-policy validation services. It does not create or
correct drafts, record a review decision, post entries or approve a filing. Bearer
scopes remain bearer scopes: the internal interactive draft/approval guards are
unchanged. A displayed preparation is not a final outgoing statutory package.

## Configuration and grants

Apply migrations through `0073_customer_expense_draft_review.sql`. Use a dedicated
non-owner, non-superuser, non-BYPASSRLS login with only these application grants:

```sql
GRANT USAGE ON SCHEMA omnixat_customer_drafts TO expense_draft_reader;
GRANT EXECUTE ON FUNCTION
  omnixat_customer_drafts.read_csv_expense_drafts(text,text,bigint,uuid,uuid,uuid)
  TO expense_draft_reader;
```

Do not grant direct omnixat/extraction schema access, schema CREATE, original-byte
reads, draft/answer writes, journal decisions, membership changes or approval rights.
Keep the DSN in a private service configuration file (mode 0600) and set
`OMNIXAT_EXPENSE_DRAFT_REVIEW_DSN_FILE`. The configured customer server shares its
existing 16-lease admission bound across database capabilities. Explicit app
construction uses `expense_draft_connection_factory`; evidence intake/spool must
also be configured. No server starts on import and no grants are applied automatically.
The website capability flag is a display hint, not authority.

## Shared read contract

With verified `records:read evidence:read` scopes, existing customer bearer transport
can read:

- `GET /v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/expense-drafts`
- `GET /v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/expense-drafts/{draft}`

Both return `{data: {items: [...], has_more: boolean}, request_id: ...}`. Listing
returns the latest 20 **eligible** preparations ordered by creation time and UUID,
with a lookahead flag; exact lookup can inspect an older known draft. The UI lists
references and opens a fresh exact read for detail. Older-page navigation remains
unfinished; this is not a complete history/audit export. Empty/unavailable sources
produce an empty listing; unavailable exact IDs return 404. Query parameters,
idempotency/write headers and POST are not supported. Routes are absent by default.
Responses use existing no-store and same-origin/HTTPS boundary controls.

The dedicated SQL function independently rechecks persisted human identity,
disabled/token cutoff/revoked membership and current tenant on every call, including
calls after outer HTTP admission. Viewer/editor/owner members may inspect. Agents
cannot use this customer reader. Token role/tenant claims do not grant authority.
The complete read chain also runs under a non-BYPASSRLS function owner in tests.
Transaction-local identity/tenant settings are cleared on release.

The existing read_csv_expense_draft function rechecks current scan policy, matching
source eligibility, blocking verdicts/live claims and open period/eligible account/
accounting date. Shared Python decoding verifies exact positive supported penny
amount and stored-pence agreement. No financial calculation is duplicated in JS.

A record includes draft ID, creation attribution/time, exact decimal amount as a
string, GBP currency, accounting date, period/account references, and source evidence/
job/cell, extracted-or-clarified origin, source attribution/time, scan policy and
fingerprint. Original bytes and credentials are never returned. Accounting period/
account labels, funding, journal decisions and correction lineage are not in this
view. Ineligible records are withheld without deleting retained preparations.

## Website and qualification limits

For CSV evidence the website offers Inspect saved expense drafts, followed by
Inspect expense draft. Refresh clears old details before requesting current data.
Stale/unavailable exact results replace the old source display. Expired/revoked
sessions clear this panel and hide workspace content; sign in again and reload to
inspect persisted records. Inspection makes no write and does not record approval.

Fixtures use fictional evidence and actual PostgreSQL/shared preparation services.
Browser tests use the gateway stand-in; independent native provider/gateway suites
remain separate. There is no claim of a complete provider-driven draft creation or
statutory approval journey. Production security/restore, OCR/model qualification,
draft creation/corrections and final-package human approval remain unfinished.

Technical source rechecked 11 November 2026:
[PostgreSQL 16 CREATE FUNCTION security-definer guidance](https://www.postgresql.org/docs/16/sql-createfunction.html).
No dependency version, legal rule or statutory amount changes are included.
