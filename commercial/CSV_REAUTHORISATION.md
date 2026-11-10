# Explicit CSV request re-authorisation

Apply migrations through 0072. A cancelled request remains cancelled. This action
creates one fresh request linked to it in PostgreSQL, with the same ordered cells,
current human attribution and token issue time, and currently eligible source and
operator-selected scan policy. It does not start a worker, post entries or approve
an accounting or statutory package.

Grant only this additional function to the existing customer request-only login:

```sql
GRANT EXECUTE ON FUNCTION omnixat_csv_requests.reauthorise_csv(text,text,bigint,uuid,uuid,uuid,uuid,timestamptz,uuid)
  TO customer_csv_requests;
```

Existing request DSN/app-factory configuration is reused. The separate reader and
requested-worker logins must not receive this grant. Reader function signature and
existing grants are retained; the historical state enum additionally recognises
reauthorised. That state means a linked replacement exists, while the parent's
cancellation actor/time and plan remain unchanged. The child appears separately
in the latest-20 request list. Full parent/child navigation is not provided yet.

POST /v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/csv-requests/{job}/reauthorisations
accepts exactly job_id (a fresh canonical replacement UUID) and cancelled_at (the
inspected parent's aware cancellation timestamp). The latter is a precondition,
not a permission or supplied event time. The body is bounded to 2048 bytes and five
seconds. Queries, duplicate/unknown fields, supplied cells/amounts and unsupported
encodings reject. X-OmniXat-Expected-Actor is mandatory. Same-origin website writes
and records:read, records:write, evidence:read, evidence:extract scopes apply.

SQL independently resolves current persisted human editor/owner membership,
identity disable/revocation/token cutoff and initiating-actor continuity. Parent
lookup is tenant/organisation/evidence bound and locked through creation. It must
still be cancelled at the exact recorded time and have no recorded result. A new
job cannot adopt an unrelated existing request. The existing request service
validates copied cells, current text/csv source bounds/fingerprint/clean verdict,
scan policy and live claims. No client-selected cells or policy are accepted here.
A unique composite parent reference permits one replacement per cancelled plan.

Exact retries under the same actor/new job reconcile the first replacement receipt
without renewing its authority. They can return that receipt even if the child is
now cancelled or its source is no longer eligible, because no new work is created.
A different attempt conflicts. A retry of the parent's original re-authorisation
never restarts a subsequently cancelled child or creates a grandchild. Starting
again from that child requires a separate explicit action bound to the child's
cancellation and a fresh job. Original request retry still cannot clear cancellation.

The requested worker rechecks the child's current authority and pinned source at
admission and storage. The parent stays ineligible for requested dispatch. Existing
cancellation/result-storage row locking remains in force. Re-authorisation creates
no ledger effect and makes no exactly-once accounting claim.

## Customer journey and recovery

Request extraction again appears on cancelled receipts for scoped editors/owners.
It explicitly retains the old cancellation and uses the exact inspected cells.
The browser freezes the replacement job, cancellation timestamp and initiating
actor for uncertain-response retries. Same-tab session recovery keeps that attempt;
a viewer can see only its pending retry, which still fails server actor/authority
checks. Confirmation refreshes actual history instead of claiming a cancelled child
was restarted. Close/reload loses pending tab state: inspect persisted history before
starting a replacement attempt. Older-page UI and full lineage browsing remain open.

The latest d3e1fdc CI rerun exposed an inspection-test readiness race: expiry was
injected before the initial asynchronous GET necessarily rendered its cancel control.
The fixture now waits for the ready control before changing the gateway token. This
does not extend timeouts, remove assertions or change runtime session handling.
The retained expiry test and all new journeys must pass in real Chromium.

Qualification uses fictional CSVs and the gateway stand-in. Independent real
provider/gateway/ClamAV and retained prototype browser checks remain required.
Production scanner/security/restore/OCR/model qualification, bounded/background
dispatch, quotas, draft approval and corrections remain unfinished.

PostgreSQL SECURITY DEFINER and row-lock semantics checked 10 November 2026:
https://www.postgresql.org/docs/16/sql-createfunction.html and
https://www.postgresql.org/docs/16/explicit-locking.html. New function uses fixed
search_path, row_security and revoked PUBLIC execute; tests include the non-BYPASSRLS
function-owner path. No legal rule, dependency or financial amount was introduced.
