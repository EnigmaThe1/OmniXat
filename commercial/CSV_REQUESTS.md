# Durable customer CSV extraction requests

Apply migrations through 0070. This opt-in path records an immutable customer cell
plan and lets an explicitly invoked worker produce candidates through the existing
CSV parser and scan gate. No daemon, automatic upload processing or ledger posting
starts. A request is not a successful extraction or filing approval.

Use a separate non-owner, non-superuser, non-BYPASSRLS customer request login:

```sql
GRANT USAGE ON SCHEMA omnixat_csv_requests TO customer_csv_requests;
GRANT EXECUTE ON FUNCTION omnixat_csv_requests.request_csv(text,text,bigint,uuid,uuid,uuid,uuid,jsonb)
  TO customer_csv_requests;
```

Configure its private DSN through OMNIXAT_CSV_REQUEST_DSN_FILE alongside the existing
record/directory, evidence spool and separate CSV-review configuration. Explicit app
construction accepts csv_request_connection_factory. No request route exists without
this opt-in. Do not grant originals, result writes, direct omnixat access, worker
functions, policy/verdict administration or approval capabilities to this login.

POST /v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/csv-requests
accepts exactly job_id and selections. job_id must be a canonical stable UUID;
selections contains 1–32 ordered objects with exactly field_name, row and column.
The shared private-plan validator enforces bounded coordinates, unique field names
and no supplied amounts. The body is bounded to 8192 bytes and five seconds;
unknown/duplicate JSON keys, query parameters and Idempotency-Key reject.
X-OmniXat-Expected-Actor is mandatory. Scopes records:read, records:write,
evidence:read and evidence:extract are required, alongside current persisted human
editor/owner membership. Token roles cannot increase authority. Website writes
retain the same-origin boundary. Provision provider scopes separately; the new
journey is not a new provider configuration or an interactive approval principal.

The SQL capability independently resolves identity disable/revocation/token cutoff
and initiating actor. It accepts only a currently eligible text/csv original up to
512 KiB, pinning its exact fingerprint/size and active operator-selected scan policy.
This is admission, not proof of well-formed CSV. The existing bounded parser runs
only in the worker. The receipt exposes job, policy and original request time.
Exact same-actor/ordered-plan retries return the original receipt; another plan,
actor, policy or pre-existing operator result conflicts. Retry never refreshes the
recorded token issue time or grants new authority. If that authority becomes invalid,
a new deliberate request is needed; there is no implicit re-authorisation.

## Explicit requested worker

Provision a separate requested-worker login with ONLY schema usage on
omnixat_extraction and omnixat_csv_requests plus these functions:

```sql
GRANT USAGE ON SCHEMA omnixat_extraction, omnixat_csv_requests TO requested_csv_worker;
GRANT EXECUTE ON FUNCTION omnixat_extraction.read_eligible_original(uuid,uuid)
  TO requested_csv_worker;
GRANT EXECUTE ON FUNCTION omnixat_csv_requests.worker_request(uuid,uuid,uuid,jsonb)
  TO requested_csv_worker;
GRANT EXECUTE ON FUNCTION omnixat_csv_requests.store_requested_result(uuid,uuid,uuid,jsonb,text,bytea,jsonb)
  TO requested_csv_worker;
```

Do not grant the customer request function, the ordinary store_csv_result function,
direct table access or schema CREATE to this worker. Set its private DSN file via
OMNIXAT_EXTRACTION_DSN_FILE. Use the existing private plan format with the exact
recorded tenant/organisation/evidence/job and ordered selections:

```bash
python -m omnixat_core.csv_extract_worker --requested --plan-file /private/requested-plan.json
```

The requested path checks the request, current persisted authority and current
source eligibility before reading and again in the result-storage transaction.
It pins the source/policy and verifies that result coordinates match the request.
A revocation between parsing and storage prevents persistence. Checks use current
statement snapshots; a permission change committed after admission to a statement
cannot interrupt that statement. Output is the existing minimal extraction receipt.
Same-job retries cannot overwrite a different result. The ordinary operator worker
path remains separate; do not use its broader credential for customer dispatch.

## Customer experience and limits

The website offers one explicit amount cell per request, with label, logical CSV
record (including headers) and column. It enters no financial amount. The API can
record up to 32 cells; a multi-cell browser editor is unfinished. Requests do not
run automatically: keep the receipt job for explicit operator processing, then use
Inspect CSV candidates. No request-history/listing/status or cancel/re-authorise UI
is provided yet. Do not create a replacement job after an uncertain response until
the exact pending request has been reconciled.

Uncertain browser saves freeze the original job/body/actor and offer exact retry.
Same-account recovery retains pending coordinates in tab memory. Close/reload loses
that state and the displayed receipt; consult the operator's durable request record
before starting another request. Request cancellation, bounded background dispatch,
history browsing and correction/draft approval remain next work. Identity or
membership revocation prevents later worker admission/storage; it does not cancel
an already admitted statement. No extraction API key or agent can approve a filing.

Tests use fictional CSVs. New browser cases use the gateway stand-in; an additional
qualification case uses actual ClamAV with synthetic rules, the request API, actual
requested-worker CLI and Chromium inspection. Independent real provider/gateway
suites remain separate. These checks do not qualify production malware coverage,
OCR/model processing or production security/restore.

SECURITY DEFINER/search_path semantics checked 10 November 2026:
https://www.postgresql.org/docs/16/sql-createfunction.html. New functions use fixed
search_path, row_security and revoked PUBLIC execute; tests exercise a non-BYPASSRLS
function owner across request/admission/store/eligibility functions. No dependency,
legal rule or financial amount was introduced.
