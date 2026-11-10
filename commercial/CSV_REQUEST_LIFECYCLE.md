# Inspecting and cancelling CSV extraction requests

Apply migrations through 0071. The existing request plan and attribution remain
immutable. Cancellation adds a timestamp and persisted cancelling identity, retaining
source references and historical receipts. It is not a deletion or filing approval.

Provision a separate non-owner, non-superuser, non-BYPASSRLS request-reader login:

```sql
GRANT USAGE ON SCHEMA omnixat_csv_request_status TO csv_request_reader;
GRANT EXECUTE ON FUNCTION omnixat_csv_request_status.read_requests(text,text,bigint,uuid,uuid,uuid)
  TO csv_request_reader;
```

No direct omnixat/omnixat_extraction/omnixat_csv_requests access, original bytes,
result writes, cancellation or schema CREATE belongs to the reader. Configure its
private DSN via OMNIXAT_CSV_REQUEST_STATUS_DSN_FILE, or explicit app construction's
csv_request_status_connection_factory, alongside evidence/spool/CSV-review config.
Only records:read and evidence:read scopes are needed. SQL independently checks a
current persisted human membership and identity disable/revocation/token cutoff.
Viewers can inspect. Token role claims cannot expand authority.

GET /v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/csv-requests
returns {items,has_more}: at most the latest 20 receipts, ordered by requested_at
then job ID descending. Older history is explicitly truncated. GET on the same
path followed by /{job} retrieves that exact job, including one outside the latest
20. Queries and write headers reject. No original, monetary candidate value, DSN,
scanner lease or fingerprint is returned. Coordinates are validated through the
shared plan validator before returning them. This is history inspection, available
even if the scan policy/source is no longer eligible.

Each receipt contains job, policy, selected coordinates, request actor/time,
cancellation actor/time and a historical state:

- awaiting_worker: no cancellation or result is recorded; this does not promise
  current dispatch authority, source eligibility or an active background worker.
- cancelled: requested-worker result storage is stopped.
- result_recorded: a result exists for that job, without claiming current source
  eligibility, successful accounting, matching financial treatment or approval.
  Inspect CSV candidates through the existing current-eligibility gate.

## Cancellation capability

Explicitly add this function to the existing separate customer request-only login:

```sql
GRANT EXECUTE ON FUNCTION omnixat_csv_requests.cancel_csv(text,text,bigint,uuid,uuid,uuid,uuid)
  TO customer_csv_requests;
```

POST /v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/csv-requests/{job}/cancellations
accepts exactly {} with Content-Type application/json (two-byte bounded body,
five-second wait). X-OmniXat-Expected-Actor is required for continuity. Same-origin
website writes and records:read, records:write, evidence:read, evidence:extract
scopes apply. SQL rechecks current persisted human editor/owner authority and token
cutoff; a viewer, agent or forged actor cannot cancel. An authorised editor/owner
can cancel a workspace request, preserving the first cancellation actor/time on
retry. Cancellation does not require current source eligibility, so stale-policy
requests can still be stopped.

A cancellation and requested-worker result storage hold the same request-row lock
through commit. If cancellation wins, admission/result storage rejects; if storage
wins, cancellation observes the recorded result and returns 409 without changing
or deleting it. This does not interrupt parsing or revoke source bytes already
admitted to memory. It does not control the separate ordinary operator extraction
path or any ledger/submission operation. Bounded lock/statement timeouts can leave
a client uncertain: retry the same job and initiating actor, then inspect receipts.

A normal request retry never clears cancellation or refreshes its authority. There
is no re-authorisation operation yet. A deliberately new request has a new job;
the old cancelled plan remains available as history. The requested-worker login
must not receive cancellation, customer-request or ordinary result-store grants.

## Customer website

Inspect extraction requests displays the latest 20 retained receipts and source
coordinates after reload. Editors can cancel an awaiting request; recorded results
and cancelled plans remain inspectable. Refresh clears old metadata before fetching;
denied sessions clear the panel and hide workspace content. An uncertain cancellation
keeps its job/actor in tab memory and offers an exact retry, even after switching
to a viewer during recovery. Displaying that pending retry grants no authority;
server actor/membership checks still apply. Pending retries outside the latest 20
remain actionable by their fixed job. Closing/reloading loses tab-only pending
state, but persisted history can now be inspected before replacing work.

The browser has no older-page navigation or direct-job lookup form yet; use the
exact-job API for older receipts. Re-authorisation, batch dispatch, request quotas,
answer corrections and human draft approval remain unfinished. No daemon starts.
Tests use fictional data and the gateway stand-in; retained independent real
provider/gateway/ClamAV and prototype browser suites remain required. Production
scanner/security/restore/OCR/model qualification remains open.

PostgreSQL function and locking semantics checked 10 November 2026:
https://www.postgresql.org/docs/16/sql-createfunction.html and
https://www.postgresql.org/docs/16/explicit-locking.html. Functions retain fixed
search_path, row_security and revoked PUBLIC execute. Tests include a non-BYPASSRLS
function owner and actual concurrent cancellation/storage transactions in both orders.
No legal rule, dependency or financial amount was changed.

## Explicit replacement requests

[CSV re-authorisation](CSV_REAUTHORISATION.md) now creates a fresh linked request
from an inspected cancellation, retaining old history and binding exact retries.
Earlier absence statements describe the initial lifecycle slice. It does not
uncancel the parent, restart a cancelled child on stale retry or start a daemon.
