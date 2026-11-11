# Customer journal review observation inspection

An optional read-only customer capability shows historical `reviewed` and
`changes_requested` observations for the exact eligible saved journal snapshot.
It does not create a decision, record a correction, post a journal, approve a filing
or submit anything. Existing internal interactive-only decision and approval guards
are unchanged. No bearer scope is removed or converted to approval authority.

## Operator configuration

Apply migrations through 0077. A separate non-owner, non-superuser, non-BYPASSRLS
application login needs only these grants:

```sql
GRANT USAGE ON SCHEMA omnixat_customer_journal_reviews TO observation_reader;
GRANT EXECUTE ON FUNCTION omnixat_customer_journal_reviews.read_observations(text,text,bigint,uuid,uuid,uuid,bytea,text) TO observation_reader;
```

Do not mix this reader with journal inspect/preview/save capabilities or grant direct
omnixat/extraction schema access, schema CREATE, decision writing or approval rights.
The separately managed function owner needs the existing shared read-function chain
and SELECT privileges under tenant RLS; the integration suite qualifies a definer
without BYPASSRLS. No table or RLS policy is relaxed by this migration.

Use a private mode-0600 `OMNIXAT_JOURNAL_OBSERVATION_DSN_FILE`; explicit construction
uses `journal_observation_connection_factory`. The configured server shares its
existing 16-lease bound. The website also needs evidence/spool, saved expense and
saved journal inspection configured. The GET route is absent without its reader.
No server/configuration/grants are activated by this change.

## API and UI contract

GET `/v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/expense-drafts/{draft}/journal-observations`
requires a verified bearer with `records:read` and `evidence:read`, and fresh persisted
human identity/membership. Viewer membership is sufficient. Token claims cannot grant
a role; agent identities are denied. There is no POST/approval route.

Required query: `snapshot_sha256`, the lowercase 64-character saved snapshot
fingerprint shown by journal inspection. Optional `after_reviewer` is the exact
returned cursor (1–200 characters, nonblank, no NUL). Unknown or duplicate query
parameters, missing/malformed fingerprints and invalid cursors return 400.

The result contains `journal_id`, `snapshot_sha256`, up to 20 `items` (reviewer_id,
decision, recorded_at), `has_more` and `next_after_reviewer`. Ordering is by reviewer
ID, using the existing bounded shared observation reader. Each request binds tenant,
organisation, evidence, expense draft, saved journal and current source/accounting
eligibility. The journal fingerprint and observation page use one statement snapshot.
A changed fingerprint returns 409 `journal_snapshot_changed`; unavailable/retained but
ineligible context returns 404. Neither is presented as an empty history. Successful
empty history means no observations for this eligible saved snapshot at that read.

Pages are live reads, not a frozen observation manifest: observations may arrive
between pages. Refresh starts from the first page; no completeness or approval claim
is inferred from reaching the end. Other-snapshot observations are not disclosed.
Corrections/reasons/answers and replaced-journal selection are not included yet.

The website exposes Inspect review observations beside a saved journal, with explicit
historical/approval boundaries, attribution/time and Load more. Refresh supersedes an
older pending page response; refresh resets pagination. Changed/unavailable snapshot
clears the old journal display and requires fresh journal inspection. Expiry or access
denial clears the containing source panel; sign-in recovery fetches fresh context.
No review observations are cached in browser storage. The UI performs no financial
calculation and provides no decision-writing or statutory approval controls.

## Qualification and next step

The six PostgreSQL tests exercise source/snapshot and tenant/evidence binding,
bounded pagination, viewer/scopes/revocation/agent checks, strict input, separate
capabilities, transaction-context cleanup and the non-BYPASSRLS definer chain. Three
real Chromium tests cover pagination/mobile/viewer inspection, changed-snapshot
clearing/refresh, and expiry/recovery. They remain mandatory in full CI, along with
the retained fictional-demo browser approval test.

Next: separately authorised human bookkeeping observations and correction journeys,
with exact saved-snapshot binding. These cannot substitute for interactive human
approval of each final statutory package. Production security/restore qualification,
operator settings/labels, complete accounting, posting, billing and qualified adapters
remain unfinished.

No dependencies or legal rules changed. PostgreSQL 16 SECURITY DEFINER/search-path
and statement-snapshot behavior were rechecked on 11 November 2026 using official
https://www.postgresql.org/docs/16/sql-createfunction.html and
https://www.postgresql.org/docs/16/transaction-iso.html.
