# Customer CSV candidate inspection

Apply migrations through 0068 using the migration owner. Provision a separate
non-owner, non-superuser, non-BYPASSRLS candidate-reader login with only:

```sql
GRANT USAGE ON SCHEMA omnixat_customer_review TO customer_csv_reader;
GRANT EXECUTE ON FUNCTION omnixat_customer_review.read_latest_csv(text,text,bigint,uuid,uuid)
  TO customer_csv_reader;
```

No omnixat/omnixat_extraction schema privileges, originals, extraction/answer writes,
ledger or approval capability belong to this login. Configure its private DSN file
through `OMNIXAT_CSV_REVIEW_DSN_FILE` alongside evidence intake/spool and existing
record/directory grants. Explicit app construction accepts
`csv_review_connection_factory`. The route/UI are disabled without this opt-in.

`GET /v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/csv-review`
requires records:read and evidence:read, a verified token and current human
membership. Viewers can inspect; role/MFA claims cannot elevate authority. The
execute-only function independently checks identity cutoff/disable/revocation,
respects forced RLS and binds tenant and organisation. Queries and POST reject.
This read-only bearer inspection does not convert the caller into an interactive
approver or strip API scopes to bypass existing human review/approval guards.

The response selects the latest currently eligible csv-amount-v1 result, ordered by
stored_at then job ID. It returns evidence/job IDs, extractor/policy versions,
SHA-256, storage time, exact decimal candidate strings, row/column references,
previously recorded attributed answers and only unanswered clarification questions.
The shared existing review decoders validate candidates/answers; malformed latest
results fail closed. Missing, blocked, stale-policy or currently claimed evidence
has no eligible review. No source original, filename, scanner lease or credentials
are returned. Refresh clears earlier displayed values before requesting new data;
denied sessions clear the candidate panel and hide workspace content.

The Inspect CSV candidates button displays source coordinates and focused
questions. Values remain candidates: inspection creates no accounting entry and
approves no filing. The first slice is read-only: it cannot submit answers, approve
an expense draft or trigger extraction. An eligible result must already have been
produced through the existing trusted extractor. PDF/image/OCR/model processing,
qualified production extraction, customer answer/draft workflows and production
scanner/security/restore qualification remain open. Latest-result selection is
explicit in the UI; historic extraction browsing remains unfinished.

Qualification tests use fictional CSVs, the real shared deterministic extractor
and generated test verdicts. They are separate from the retained real-daemon and
provider/gateway tests; they do not prove production malware coverage or a real
provider-driven extraction journey. No real records or credentials are fixtures.

PostgreSQL SECURITY DEFINER/search-path semantics rechecked **10 November 2026**:
https://www.postgresql.org/docs/current/sql-createfunction.html. New capability
uses fixed search_path, row_security and revoked PUBLIC execute. Tests include a
non-BYPASSRLS migration owner throughout the review/eligibility function chain.

## Explicit extraction prerequisite

The [trusted CSV worker](CSV_EXTRACTION_WORKER.md) can now populate candidates
from a private operator-selected plan through the existing scan/extraction gate.
It exposes no customer HTTP trigger or automatic processing service.
