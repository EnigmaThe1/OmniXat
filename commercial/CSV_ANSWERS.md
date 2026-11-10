# Customer CSV clarification answers

Apply migrations through 0069. This opt-in capability extends candidate inspection
with one focused answer at a time. Saving an answer retains the original candidate;
it does not change source bytes, post entries or approve a draft or filing.

Provision a separate non-owner, non-superuser, non-BYPASSRLS answer-only login:

```sql
GRANT USAGE ON SCHEMA omnixat_customer_answers TO customer_csv_answers;
GRANT EXECUTE ON FUNCTION omnixat_customer_answers.answer_csv(text,text,bigint,uuid,uuid,uuid,uuid,text,integer,integer,text)
  TO customer_csv_answers;
```

No direct omnixat, omnixat_extraction or customer-review grants belong to this login.
Configure its private DSN via OMNIXAT_CSV_ANSWER_DSN_FILE, alongside the separate
CSV review DSN, intake spool and record/directory grants. Explicit app construction
accepts csv_answer_connection_factory. Without this opt-in no answer route exists.
The existing candidate-reader login remains read-only.

POST /v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/csv-answers
accepts exactly job_id, field_name, row, column and amount in a JSON object (2048
bytes, five-second body limit). job_id is the canonical inspected extraction UUID.
The cell must match an unresolved original candidate. amount must be an exact
signed decimal string (up to 18 integer and six fractional digits) or explicit null
for unavailable; no floats, currency symbols, grouping separators or inferred zero.
Unknown/duplicate fields, invalid coordinates and numeric JSON amounts reject.
Queries, content encodings and Idempotency-Key reject. X-OmniXat-Expected-Actor is
required for continuity and can restrict, never grant, authority. Customer website
writes also require its configured same-origin boundary.

Bearer scopes records:read, records:write, evidence:read and evidence:clarify are
required. SQL independently resolves current persisted human editor/owner membership,
identity disable/revocation/token cutoff and the initiating actor. Token roles cannot
increase authority. No bearer principal is converted into interactive filing approval.
Attribution comes from the persisted identity, never a supplied actor body field.
The existing store_csv_answer service checks tenant, organisation, exact job/cell,
active policy and current source eligibility. A blocked/stale/currently claimed source
rejects even an answer retry. This is a transaction-time authority check, not a promise
to cancel writes already admitted before a concurrent permission change commits.

The first answer is immutable. Exact retries by the same actor return its original
timestamp; changed text/scale/actor conflicts (409). A success receipt contains only
job/evidence/cell/time; inspect candidates to see attributed answers. No overwrites or
answer correction UI exists yet. Do not retry uncertain writes with a new job or
changed answer. Reconcile the exact pending request first.

The browser offers exact decimal or explicitly unavailable input, keeps a pending
request in tab memory, freezes edits after an uncertain response and retries its
original job/body/actor. Membership/session failure clears candidate DOM; pending
request state stays in the tab for same-account recovery. Reloading the page loses
unsent/tab-only retry state; inspect saved answers before starting another answer.
The UI prevents ordinary navigation/refresh from discarding a dirty answer; browser
close/crash and general draft persistence remain open. Answers are offered one at a
time; previously recorded answers remain visible after reload.

Tests use fictional source data and the existing gateway stand-in. Independent real
provider/gateway, ClamAV and retained prototype browser suites remain required.
This capability does not qualify production malware/OCR/model processing, extraction
requests, draft review/posting, correction history or statutory human approval.

PostgreSQL SECURITY DEFINER semantics checked 10 November 2026:
https://www.postgresql.org/docs/16/sql-createfunction.html. The additive function
uses fixed search_path, forced RLS and revoked PUBLIC execute. Tests exercise a
non-BYPASSRLS migration owner through the answer/eligibility function chain.
