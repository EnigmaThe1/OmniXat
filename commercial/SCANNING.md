# Trusted scanning and customer status

This increment connects the existing quarantine/scan-claim services to a bounded
ClamAV INSTREAM adapter and provides read-only status in the customer website.
It is opt-in infrastructure, not an automatic processing pipeline or production
malware-coverage claim. Originals remain in quarantine. No extraction, ledger
entry, filing or payment is started by these routes. Customers can explicitly
record durable scan requests; only the explicit trusted worker processes them.

## Customer read capability

Apply checksum-checked migrations through **0066** with the migration owner.
Create a separate non-owner, non-superuser, non-BYPASSRLS status login. Grant only:

```sql
GRANT USAGE ON SCHEMA omnixat_evidence_status TO customer_status_reader;
GRANT EXECUTE ON FUNCTION omnixat_evidence_status.read_status(text,text,bigint,uuid,uuid)
  TO customer_status_reader;
```

Do not grant this login schema access to `omnixat`, originals, scan claims, verdict
writes or active-policy administration. Supply its DSN in a private file through
`OMNIXAT_SCAN_STATUS_DSN_FILE` alongside the existing private evidence spool and
record/directory grants. The web process must not receive the scanner DSN, scanner
socket or policy-administration credentials. The app factory additionally accepts
`scan_status_connection_factory` for explicitly constructed service integrations.

`GET /v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/scan-status`
requires a verified token with records:read and evidence:read and a fresh persisted
membership. The separate SQL capability rechecks identity cutoff/revocation and
membership, respects forced RLS, and binds both tenant and organisation. It returns
only evidence ID, active policy version, status and observation timestamp. It cannot
read original bytes, reveal claim tokens or change a verdict. Client-selected policy
queries and POST requests are rejected.

| Status | Meaning |
|---|---|
| upload_incomplete | No stored original; upload the same file again |
| not_configured | Operator has not selected an active qualified scan policy |
| awaiting_scan | No current-policy observation or live claim; this does not mean queued |
| requested | A durable current-policy request exists; awaiting an operator-run worker |
| scanning | A live current-policy worker claim exists |
| blocked | A blocked current-policy observation exists; it takes precedence |
| scanned | A clean exact-byte observation exists under the active policy with no live claim |

Old-policy observations cannot become current merely by refreshing the page. The
status display is a point-in-time observation; it grants no extraction authority.
The existing extraction gate must recheck current policy/claims/verdicts itself.
The customer can refresh status, but cannot submit a verdict or choose a scanner.

## Customer scan requests

Provision a **separate** non-owner, non-superuser, non-BYPASSRLS request login:

```sql
GRANT USAGE ON SCHEMA omnixat_evidence_requests TO customer_scan_requester;
GRANT EXECUTE ON FUNCTION omnixat_evidence_requests.request_scan(text,text,bigint,uuid,uuid,uuid)
  TO customer_scan_requester;
```

Give this login no direct omnixat schema/table privileges, scanner functions or
policy/verdict writes. Configure a private `OMNIXAT_SCAN_REQUEST_DSN_FILE` (or
`scan_request_connection_factory`) as well as status access and evidence intake.
The customer sees Request scan only for an awaiting-scan item when the current
human owner/editor has records:read, records:write, evidence:read and evidence:scan.
`evidence:register` alone does not grant scan requests. The optional scope must be
provisioned by the trusted identity provider; token role claims cannot grant it.

`POST /v1/workspaces/{tenant}/organisations/{organisation}/evidence/{evidence}/scan-requests`
accepts only the exact JSON body `{}` with Content-Type application/json, no query,
encoding or idempotency-key. Same-origin gateway rules apply. The optional expected
actor header restricts account continuity. It returns 202 and evidence_id,
policy_version and requested_at; this is a durable request receipt, not completion.
The unique tenant/evidence/current-policy key makes retries/concurrent requests
return the same first receipt and attribution. The SQL capability rechecks human
membership/cutoff on every invocation and locks the policy through commit; policy
comes from the operator, never the client. Incomplete/missing uploads or no policy
cannot enqueue. Request admission does not continuously lock member authority.

Status precedence retains blocked/scanning/scanned before requested. Old-policy
requests do not enable work under a newer policy; the customer can request the new
policy separately. A receipt persists after requester revocation but worker
admission rejects disabled/revoked/downgraded identities or a newer token cutoff.
Status requested means a historical durable request exists, not guaranteed current
authority or an active scheduled processor. Cancellation/re-authorisation of the
same-policy first request, enumeration/dispatch and automated retries remain open.
No request table, requester identifiers, token timestamps or original bytes are
exposed by status. No bearer token is stored in the request record.

## Explicit worker

The worker uses the existing dedicated scanner grants in [EVIDENCE.md](EVIDENCE.md),
separate from intake, status, extraction and policy administration. It checks stored
byte length/fingerprint, uses recoverable 120-second claims, calls the scanner outside
the transaction, then persists the result only while its claim remains live. A
same-policy retry reuses the durable receipt. Scanner failure leaves no clean result.

Provide two private, regular, service-owned files (mode 0600):
`OMNIXAT_SCANNER_DSN_FILE` and `OMNIXAT_SCANNER_CONFIG_FILE`. Configuration fields:

```json
{
  "socket_path": "/run/omnixat-scanner/clamd.sock",
  "expected_version": "ClamAV <operator-qualified exact VERSION response>",
  "policy_version": "<operator-qualified immutable policy ID>"
}
```

These are placeholders, not working release settings. Run explicitly from commercial:

```bash
python3 -m omnixat_core.scan_worker --tenant TENANT_UUID \
  --organisation ORGANISATION_UUID --evidence EVIDENCE_UUID
```

For customer-requested work, separately grant the scanner login:

```sql
GRANT USAGE ON SCHEMA omnixat_evidence_requests TO scanner_worker;
GRANT EXECUTE ON FUNCTION omnixat_evidence_requests.worker_request(uuid,uuid) TO scanner_worker;
```

Add `--requested` to the command. Admission requires a current-policy durable
request, matching configured qualified policy, and still-authorised requester.
The check happens before the existing bounded scan; it is not continuous
cancellation of an in-flight scan. The earlier command without this flag remains
an explicit operator-authorised single-item tool. No scheduled processor starts.

Scope must come from an operator-authorised task; never dispatch arbitrary browser
IDs directly to this worker. No service starts on import. The worker returns a
minimal receipt and generic failure, never originals, passwords or daemon diagnostics.
It exposes no HTTP endpoint and never promotes a policy to active status.

The adapter accepts only a server-selected private Unix socket and bounded bytes
(up to the existing 20 MiB cap), sends NUL-framed commands and network-length chunks,
requires an exact VERSION response before and after the stream, and bounds the
whole operation to 30 seconds and replies to 4096 bytes. Only exact stream OK or a
single FOUND record produces a result; errors, malformed/truncated replies, drift,
timeouts and socket failures are unavailable, never clean. Signature names are not
returned to customers. No URL, daemon-visible file path, TCP, shell, reload or
shutdown command is accepted through the adapter.

## Qualification and remaining gates

Production operation requires a qualified immutable scanner configuration and
signature manifest for each policy ID, protected socket directories/groups, daemon
isolation, patched engine, fresh approved signature coverage, conservative archive,
encryption and resource-limit handling, and bounded worker admission/monitoring.
VERSION checks detect ordinary engine/database drift; they do not attest all daemon
settings or custom database contents. Do not reload/change a daemon behind an
unchanged policy/socket or reuse policy IDs for different configurations. A clean
response is not a guarantee that a file is harmless or its figures are correct.

CI installs the maintained official Ubuntu daemon package and prints the observed
version. `scanner_tests` starts a separate non-root local daemon with a **harmless
synthetic NDB marker only**, in private temporary storage with self-check disabled.
It exercises actual streaming, detection, the worker/receipt, customer status and
Chromium, plus failure/retry behaviour. This proves the adapter/service path, not
real malware/signature coverage. No official database is promoted to production,
no real customer file is used and private daemon logs are not uploaded.

```bash
# Disposable PostgreSQL DSN, requirements-web-tests and Chromium are prerequisites.
PYTHONPATH=.:integration_tests OMNIXAT_CLAMD_BINARY=/usr/sbin/clamd \
  python3 -m unittest discover -s scanner_tests -v
```

Sources checked **10 November 2026**: [ClamD protocol](https://docs.clamav.net/manual/Usage/ClamdProtocol.html),
[extended signatures](https://docs.clamav.net/manual/Signatures/ExtendedSignatures.html),
[signature target types](https://docs.clamav.net/appendix/FileTypes.html), and the
[official Ubuntu package](https://packages.ubuntu.com/noble-updates/clamav-daemon).
No legal rule or financial amount changed in this increment. Durable customer
request dispatch/cancellation/re-authorisation, qualified extraction and draft
review remain subsequent work.

PostgreSQL capability/RLS semantics checked **10 November 2026** against the
[official row security documentation](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
and [SECURITY DEFINER guidance](https://www.postgresql.org/docs/current/sql-createfunction.html).
New functions fix search_path, enable row_security and revoke PUBLIC execute.
Tests include a non-BYPASSRLS migration owner with forced RLS.

## Explicit bounded requested batch

Run `python -m omnixat_core.scan_worker --tenant TENANT_UUID --organisation
ORGANISATION_UUID --batch-file /private/operator-manifest.json` from commercial.
The manifest is a private service-owned JSON array of one to five distinct canonical
evidence UUID strings; never publish a real manifest or accept it as an HTTP body.
All IDs are validated before any item starts. Tenant/organisation apply to every
item. Batch mode always requires current-policy customer requests and freshly
checks requester authority for each item, even without --requested. Scanner config,
credentials, policy checks, claims and verdict persistence use the existing services.

The command emits one JSON receipt per completed item and stops at the first
failure with a nonzero exit. Earlier receipts remain committed; the unprocessed
suffix is not a successful batch. Operator retry of the same manifest reuses the
existing durable verdicts. This is a five-item work cap, not a strict overall wall
clock SLA: existing per-scan and database timeouts still apply. No background
service, queue enumeration, automatic retry, cancellation or ledger effect starts.

## Customer cancellation

Grant the request login this additional capability only after migration 0066:

```sql
GRANT EXECUTE ON FUNCTION omnixat_evidence_requests.cancel_scan(text,text,bigint,uuid,uuid,uuid)
  TO customer_scan_requester;
```

`POST .../evidence/{evidence}/scan-cancellations` takes the same exact `{}` body,
scopes, current human owner/editor membership, origin and optional expected-actor
constraint as requesting. It cancels only the operator's current policy and retains
the original request plus first cancellation time/actor. Concurrent retries do not
change that attribution. No direct table UPDATE grant is needed. The response is
the original request receipt; refresh status to observe cancellation.

The website offers Cancel scan request for requested items and shows cancelled
status after refresh/reload. A cancellation prevents future --requested/batch
admission. It cannot interrupt a scan already admitted, revoke an existing verdict
or delete an original. Status preserves blocked, live scanning and scanned
observations ahead of cancellation. The explicit operator single-item mode remains
independent. Normal request retries cannot re-authorise a cancelled same-policy
request; a new operator policy has a separate request. Re-authorisation with
preserved history remains unfinished. This supersedes earlier cancellation-pending
notes; automated dispatch and production scanner qualification remain open.

SECURITY DEFINER/search-path semantics rechecked 10 November 2026 against
https://www.postgresql.org/docs/current/sql-createfunction.html. Cancellation
retains forced tenant RLS and separately revoked PUBLIC execute.
