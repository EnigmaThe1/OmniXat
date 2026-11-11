# Customer expense funding context

The optional customer funding workflow records an explicit configured payer/source
for an eligible saved expense preparation. It does not move money, connect a bank,
verify payer ownership, classify tax treatment, post a journal or approve a filing.
Internal interactive-only funding and approval services remain unchanged: no bearer
scopes are stripped and no approval principal is constructed.

## Configuration and separate grants

Apply migrations through 0075. Keep read/write capabilities on separate non-owner,
non-superuser, non-BYPASSRLS logins. Application grants are:

```sql
GRANT USAGE ON SCHEMA omnixat_customer_funding TO funding_reader, funding_writer;
GRANT EXECUTE ON FUNCTION
  omnixat_customer_funding.read_funding(text,text,bigint,uuid,uuid,uuid)
  TO funding_reader;
GRANT EXECUTE ON FUNCTION
  omnixat_customer_funding.record_funding(text,text,bigint,uuid,uuid,uuid,uuid,uuid,uuid)
  TO funding_writer;
```

Do not mix reader/writer grants or grant direct omnixat/extraction access, schema
CREATE, policy/identity administration, journal or approval rights. Use private DSN
files (mode 0600) in `OMNIXAT_EXPENSE_FUNDING_READ_DSN_FILE` and
`OMNIXAT_EXPENSE_FUNDING_WRITE_DSN_FILE`. Explicit app construction uses
`expense_funding_read_connection_factory` and
`expense_funding_write_connection_factory`; the configured server shares its existing
16-lease bound. Evidence/spool and saved expense draft inspection must also be enabled
for the website. Routes are absent unless the corresponding capability is configured.
No server starts, configuration is activated or grants are applied automatically.

Funding sources are separately operator-managed configuration with opaque payer/source
references and business_funds/personal_funds type. They are not bank credentials,
accounts, verified legal ownership or a bank-feed consent. No source or payer is
invented or created by this form. Settings management/account labels remain unfinished.

## API and authority

The shared path is:
`/v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/expense-drafts/{draft}/funding`.

GET requires verified records:read/evidence:read and fresh persisted human membership.
It reuses existing funding and expense readers, including current source/scan/
accounting eligibility. The response data contains:

- `funding`: null if none recorded, otherwise source ID, payer ID, funding type,
  recorded actor/time and source_eligible flag. A disabled funding source remains
  visible in retained history with source_eligible false; it is not treated as enabled.
- `choices`: first 20 currently eligible configured sources, each with ID, payer ID
  and type, ordered by source UUID; `has_more` indicates additional choices. Viewer
  memberships and tokens without records:write receive no selection choices.

POST requires records:read/records:write/evidence:read, an expected initiating actor
header, and exact JSON `{funding_source_id, payer_id}` with canonical nonzero UUIDs.
The source/payer pair must match current enabled configuration. Funding type, actor,
amount, timestamps and approval fields are not accepted. JSON is bounded to 2048
bytes/five seconds through the existing strict JSON transport. Query/idempotency
parameters and unsupported fields fail. Successful 200 replies contain the stable
funding receipt; exact same actor/pair retries reconcile it, while different recorded
choices/actors conflict. No update/delete/correction endpoint is provided.

SQL independently checks current human editor/owner membership, cutoff/disabled/
revoked identity and expected actor. Existing preparation lock-only RLS policies
allow identity/membership row locks without granting direct runtime mutations. The
writer also locks the saved draft, active policy, accounting context and quarantine
observations until commit, then reuses record_expense_funding_context to enforce
current source eligibility and immutable funding selection. Scope includes exact
organisation/evidence/draft, not just a tenant ID. Readers cannot invoke writer
capabilities. Transaction-local settings are cleared on release. Tests qualify the
complete read/write chain under a non-BYPASSRLS function owner and demonstrate that
revocation, policy/context/source changes and a new blocked verdict cannot race the
held write gates. No exactly-once ledger effect is claimed.

## Website and recovery

From saved expense draft detail, Inspect funding asks Who funded this expense?
An editor explicitly selects a configured payer/source pair with no default. After
recording, a fresh read displays actual retained type, payer/source references,
attribution and current source availability. A viewer can inspect retained context.
Refresh clears old details first. Expiry clears the parent draft/source display;
same-tab recovery restores the original pending pair and actor for exact retry.

Uncertain saves freeze the pair/actor; another account cannot reattribute the attempt.
No fresh write is inferred from a lost receipt. Pending memory is tab-only and is lost
on close/reload. Current eligibility changes can prevent receipt confirmation or
withhold the entire expense draft. Empty/ineligible inspection does not prove that
no earlier commit exists; reconcile retained records before replacing work. A disabled
source remains inspectable if the expense draft itself remains eligible.

Funding corrections, journal preparation/review/corrections, bank reconciliation,
full source pagination and final human exact-package approval remain unfinished
customer journeys. New browser tests use fictional records and the gateway stand-in;
independent real provider/gateway/scanner suites remain separate. This does not qualify
production security/restore, bank arrangements, OCR/model or statutory submission.

Technical sources rechecked 11 November 2026: PostgreSQL 16
[CREATE FUNCTION](https://www.postgresql.org/docs/16/sql-createfunction.html) and
[explicit locking](https://www.postgresql.org/docs/16/explicit-locking.html).
No dependency version, legal rule or statutory amount changes are included.
