# Customer CSV expense preparation

The optional customer form/API saves a source amount and an expense preparation in
one transaction through existing validated SQL services. It is not a journal posting,
a correction workflow, a tax treatment decision or statutory approval. Internal
interactive-only Python services remain unchanged: bearer scopes are never stripped
and no approval principal is constructed.

## Configuration

Apply migrations through 0074. Use a dedicated non-owner, non-superuser,
non-BYPASSRLS login with these application grants only:

```sql
GRANT USAGE ON SCHEMA omnixat_customer_preparation TO expense_preparer;
GRANT EXECUTE ON FUNCTION
  omnixat_customer_preparation.expense_choices(text,text,bigint,uuid,uuid)
  TO expense_preparer;
GRANT EXECUTE ON FUNCTION
  omnixat_customer_preparation.create_expense(text,text,bigint,uuid,uuid,uuid,uuid,text,integer,integer,uuid,uuid,date)
  TO expense_preparer;
```

Do not grant this web login direct omnixat/extraction access, schema CREATE, identity
updates, policy administration, ledger or approval privileges. Set the private DSN
file (mode 0600) in `OMNIXAT_EXPENSE_PREPARATION_DSN_FILE`; explicit construction uses
`expense_preparation_connection_factory`. The configured server retains its shared
16-lease database bound. Evidence/spool must be configured; the website also needs
CSV candidate review enabled. Configure the separate saved-draft reader for subsequent
inspection. No server starts on import and no grants/configuration are activated here.

Bookkeeping periods and expense account references are separately operator-managed
configuration. This increment cannot invent or create them. No statutory accounting
period or tax treatment is inferred from a period/account selection.

## Shared API contract

Both actions require verified `records:read records:write evidence:read` scopes and
fresh persisted human owner/editor membership. Agent, viewer, disabled, revoked and
cutoff identities cannot prepare drafts, even if token role claims say otherwise.

- GET `/v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/expense-choices`
  returns up to 20 open bookkeeping periods (ID/start/end) and eligible expense
  accounts (ID), with independent has_more_periods/has_more_accounts flags. These are
  configuration choices, not proof that a source is currently eligible. Older-choice
  navigation and account labels are unfinished.
- POST the same base `/expense-drafts`, with `X-OmniXat-Expected-Actor` and exact JSON:
  `{job_id, field_name, row, column, period_id, expense_account_id, accounting_date}`.
  IDs are canonical UUID strings; accounting_date is explicit `YYYY-MM-DD`.
  Source coordinates use the shared CSV bounds. No amount, currency, actor, approval
  or posting field is accepted. The JSON body is limited to 2048 bytes/five seconds;
  duplicate/non-finite/deep malformed JSON and extra query/idempotency headers fail.
  A successful 201 response contains the stable saved `{id, created_at}` receipt.

The amount is derived from the recorded extracted cell or prior attributed
clarification through create_csv_draft_amount. create_csv_expense_draft then checks
current source/policy, open period/date, eligible account, GBP and exact positive
penny support. Both steps are atomic: unavailable source, context, amount or conflicting
retry raises and rolls back the whole attempt, including a newly inserted amount.
The source/job/field natural key permits one immutable preparation. Exact actor/
source/accounting retries return its receipt; changed context or actor conflicts.
It does not deduplicate the same economic event across different extraction jobs.

SQL independently resolves the current identity, checks the expected initiating
actor and holds identity/membership row locks until commit. Existing source/policy/
accounting lock gates remain in use. Migration 0074 adds narrowly filtered UPDATE
visibility policies for locking the current identity/membership, with WITH CHECK(false)
to reject actual mutations under RLS. It grants no runtime UPDATE rights. Tests run
the complete write chain under a non-BYPASSRLS function owner and verify that even
that owner cannot use these policies to change identity/membership data. Function
owners need the existing table privileges required by their SQL, including row-lock
privileges; runtime roles must remain separate.

## Website and retry limits

From Inspect CSV candidates, an editor can select Prepare expense draft, explicitly
choose a resolved source cell, configured period/account and accounting date, then
Save expense draft. There is no entered amount and no default date/account/period.
The form explicitly states GBP-only support and asks the user to confirm the source
currency before saving; no currency is inferred from the numeric CSV cell. The
existing saved-draft view can inspect the resulting exact amount and provenance.
This does not record a review/approval decision or create a final filing package.

An uncertain save freezes the original payload and initiating actor for Retry expense
preparation. Account switching cannot reattribute that attempt. Session expiry clears
source details and permits same-tab recovery with the original selection; fresh
server authority is still required. Changed/revoked authority or stale policy/context
can prevent retry confirmation even when an earlier result was committed. Inspect
persisted saved drafts before replacing uncertain work. Current eligibility may
withhold a stale saved draft; an empty listing is not proof that no earlier commit
exists. Operator reconciliation may be required. Closing/reloading the tab
loses pending attempt memory; it does not undo saved preparations.

Tests use fictional records and the browser gateway stand-in. Independent provider/
gateway/scanner suites remain separate; no complete production preparation, restore,
OCR/model or statutory approval qualification is claimed. Funding, journal review,
corrections and final-package human approval remain unfinished customer journeys.

Technical sources rechecked 11 November 2026: PostgreSQL 16
[CREATE FUNCTION](https://www.postgresql.org/docs/16/sql-createfunction.html),
[CREATE POLICY](https://www.postgresql.org/docs/16/sql-createpolicy.html),
[explicit locking](https://www.postgresql.org/docs/16/explicit-locking.html).
No dependency version, legal rule or statutory amount changes are included.
