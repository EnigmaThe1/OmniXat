# OmniXAT autonomous development handover

## Authorised objective

Build a commercial UK AI accounting and compliance platform: multiple customers,
subscriptions/trials, paid developer API, platform-owner administration, autonomous
document processing/bookkeeping/reconciliation, and consented business bank feeds.
Statutory filing always needs explicit human review and approval of the final package.
The owner explicitly authorised continuing development and commits/pushes to GitHub
on 5 November 2026. This does not authorise paid contracts, production deployment,
customer data publication or statutory submissions.

## Canonical work

- Repository: https://github.com/EnigmaThe1/OmniXat
- Development branch: `commercial/compliance-foundation-20261105`
- Checkout convention: `/srv/playground_dev/OmniXat`
- Historical base: `5dd49db`, fictional v0.4 family demo.
- Earlier commercial commits: `365379f`, then `bcfaa7c`.
- The current branch tip and its files are authoritative, not these historical SHAs.
- Read `COMMERCIAL_SPEC.md`, `AI_AND_BANKING_SPEC.md`, `DEVELOPMENT_STATUS.md`,
  `UK_COMPLIANCE_RESEARCH_2026-11-05.md`, and `commercial/README.md` before editing.
- The separate `feat/personal-foundation` branch contains an earlier authenticated
  single-owner FastAPI/PostgreSQL prototype. Inspect before reusing; do not replace
  commercial work with it or claim it provides tenant isolation.

## Every-run recovery protocol

1. Read applicable AGENTS.md and the principal-first policy when accessible. Never
   publish private records, credentials, account codes, financial documents or logs.
2. Fetch repository/branch metadata. If the checkout is missing, clone the repository
   under the checkout convention and select the existing development branch. Do not
   create a replacement branch from main if the development branch cannot be found.
3. Inspect branch, HEAD, git status, recent commits, remote tip and open PRs/checks.
   Never run reset --hard, clean, force-push, blanket checkout, or overwrite another
   worker's changes. A dirty tree is work to understand, not rubbish to discard.
4. Run `python3 scripts/development_checkpoint.py` after fetching. A refusal means
   inspect/reconcile first. If behind, fast-forward only after confirming a clean
   tree and reread changed files. Divergence/concurrent edits require deliberate
   reconciliation; never force the remote to match local state.
5. Read this handover and the status file, then inspect the actual code and tests for
   the next task. Treat historical test totals as evidence, not an instruction to
   suppress new failures. Do not reimplement a feature already present.
6. Select one coherent next increment; record its scope and in-progress state in
   DEVELOPMENT_STATUS.md before substantial work. Resolve legitimate existing
   blockers in that scope. Keep the existing demo separate.
7. Implement and test. Recheck current official documentation for changed dependencies,
   legal rules or integrations. Record what ran and distinguish unavailable prerequisites
   from code failures. Do not describe mocked or sandbox operation as live.
8. Update DEVELOPMENT_STATUS.md with completed work, known limits, exact commands,
   outcomes and the next unfinished step. If interrupted, recover from git diff,
   code and tests, rather than blindly rerunning prior mutations.
9. Review the staged diff for secrets/private information and unintended changes.
   Commit only the intended changes. Fetch again and compare the remote tip. Push
   to the development branch using ordinary fast-forward protection. If the remote
   moved, review its changes before integrating; never force-push. A local commit
   is not proof of a successful GitHub push.
10. Verify the pushed commit against the remote. Report a concise outcome with commit,
    test evidence, blockers and next step. If tools or access are unavailable, say so;
    do not fabricate execution or claim future runs can certainly execute tools.

## Concurrency and interruptions

Only one writer should use a checkout. Prefer an isolated per-run worktree when
another worker is active. A run must not merge main, approve/merge a PR or deploy
automatically. Git push rejection is a concurrency signal to investigate, not a
reason to rewrite history. Scheduled start times are targets, not proof a previous
run finished. Do not automatically start a second implementation of an active task.

Remote commits plus a current status document are the durable recovery checkpoint.
Never rely on this conversation, scratch files, local-only memory or a running
process surviving to the next run. Save useful work before running long operations.
If a change is incomplete, use a clearly labelled WIP commit only after checking
that it introduces no active public service or private material; record failing
checks honestly. Do not add invented progress merely to make a scheduled report.

## Next direction

Implement durable tenant-scoped backend services and maintained identity integration;
then owner administration, persistent pricing and hosted billing sandbox. Build AI
document/ledger workflows on the same services; qualify bank and filing adapters
separately. The first PostgreSQL organisation/note schema and tested RLS repository now exist
(see `commercial/POSTGRES.md`); membership/revocation and identity integration are next.
The maintained identity system, complete production persistence qualification, full
ledger, owner UI, actual AI provider, bank connector and filing transport are not
already delivered by the existing domain contracts.

## Local verification

```bash
cd /srv/playground_dev/OmniXat/commercial
python3 -m unittest discover -s tests -v
```

The historical fictional-demo browser test requires Chromium. Do not silently skip
or delete it to report a green full-suite result. No real user data is needed for
development tests. Do not use public GitHub issues as private planning/evidence packs.

## Latest C1 checkpoint

PostgreSQL first record slice: 32 offline tests and 22 integration tests pass.
Read the latest DEVELOPMENT_STATUS.md and commercial/POSTGRES.md for exact evidence
and limits. Integration requires an explicit disposable-cluster DSN; no automatic
skip. It creates/drops its own random test database and role. The historical demo
still has the known missing-Chromium failure. Next work is persistent membership
and identity verification, not another replacement of this schema.

## Latest identity checkpoint

The C1 second slice adds persistent identity/membership/revocation plus signed bearer
verification, with **32 core, 9 token and 37 PostgreSQL tests passing**. Migration 0001
is unchanged; 0002 is additive and upgrade-tested. Read `commercial/IDENTITY.md` and
the latest status for exact boundaries. Next is shared authenticated HTTP/API service
work and maintained-provider login qualification. Do not rebuild membership storage
or mistake synthetic signed-token tests for a live OIDC login integration. Bearer
principals have records-only scopes and no filing-approval or staff authority.

## Latest HTTP checkpoint

C2 first slice adds bearer-only ASGI organisation/note create/read routes using shared
identity/membership/repository services. **32 core, 9 token and 58 database/HTTP tests
pass**; the historical demo still has its known missing-Chromium failure. Read
`commercial/HTTP_API.md` and the latest status. No listener starts automatically.
Next: persistent creation idempotency/result reconciliation and minimal audit before
autonomous retries. Do not duplicate these routes or expose trusted Principal input.
Maintained-provider login, quotas and deployment remain unqualified; no approval,
filing, billing or bank route exists in the new transport.

## Latest creation receipt checkpoint

C2 retry protection is complete for organisation/note creates: migration 0003,
tenant/actor/operation-scoped keys, same-transaction receipts and replays, conflict
and revoked-access checks. **32 core, 9 token and 68 PostgreSQL/HTTP tests pass**.
Read the latest status and HTTP_API.md. Next: persistent versioned plans/prices and
owner audit for a billing sandbox, without payment activation. The demo Chromium
prerequisite remains missing; no live provider or statutory integration exists.

## Latest pricing checkpoint

Migration 0004 and the internal staff catalogue persist plans, scheduled prices
and owner audit using a dedicated database login. See commercial/PRICING.md for
grants and limitations. **32 core, 9 token and 76 PostgreSQL/HTTP tests pass**;
the unchanged demo browser test requires Chromium. Next: tenant-scoped sandbox
subscriptions with pinned versions and state validation. No payment integration,
staff HTTP route or live service is enabled.

## Latest subscription sandbox checkpoint

Migration 0005 adds isolated sandbox subscriptions and cancellation records,
with pinned prices, trial expiry and no paid activation. See
commercial/SUBSCRIPTION_SANDBOX.md. **32 core, 9 token and 84 PostgreSQL/HTTP tests
pass**; the unchanged demo browser test requires Chromium. Next: authenticated,
deduplicated sandbox event handling and reconciliation. No payment provider,
customer route or live entitlement is enabled.

## Latest simulator event checkpoint

Migration 0006 adds HMAC-verified, tenant-scoped local event receipts and
price/state reconciliation without subscription mutation. See
commercial/SANDBOX_EVENTS.md. **32 core, 9 token and 91 PostgreSQL/HTTP tests
pass**; the unchanged demo browser test requires Chromium. Next: an owner-only
aggregate sandbox metrics service, with no live revenue claims or customer
record access. No provider, payment or deployment enabled.

## Latest owner sandbox metrics checkpoint

Migration 0007 and an internal service report current sandbox subscription states
and stored reconciliation outcomes as counts. See commercial/SANDBOX_METRICS.md.
**32 core, 9 token and 96 PostgreSQL/HTTP tests pass**. The unchanged demo browser
case could not launch Chromium due to a runtime socket permission error. Next:
qualify a maintained interactive staff identity adapter and revocation before
adding any owner HTTP route. No live billing or deployment was enabled.

## Latest staff identity checkpoint

Migration 0008 and the internal callback adapter verify a staff ID token
and look up current membership, role and revocation separately from tenant
bearer access. See commercial/STAFF_IDENTITY.md. **32 core, 15 identity and
101 PostgreSQL/HTTP tests pass**. The unchanged demo Chromium test still
fails on a launch socket permission error. Next: one-time login transaction
storage, revocable staff sessions and specific provider qualification before
any owner HTTP route. No real identity provider or deployment was enabled.

## Latest one-time staff login checkpoint

Migration 0009 and the internal PostgreSQL store persist five-minute browser-
and configuration-bound login transactions. Consumption commits once before
releasing PKCE material. See commercial/STAFF_LOGIN.md. **32 core, 15 identity
and 109 PostgreSQL/HTTP tests pass**. The unchanged demo Chromium test fails
because this environment denies its launch socket. Next: bounded revocable
staff sessions, then provider qualification and browser wiring. Nothing live
was activated or deployed.

## Latest revocable staff session checkpoint

Migration 0010 and the internal session store add opaque sessions with a fixed
MFA deadline, current directory checks and logout revocation. See
commercial/STAFF_SESSIONS.md. **32 core, 15 identity and 117 PostgreSQL/HTTP
tests pass**. The unchanged demo Chromium test still fails on the environment's
socket permission restriction. Next: qualify a specific identity provider and
wire the browser flow with the listed controls before exposing owner routes.
Nothing live was activated or deployed.

## Latest Keycloak code-flow checkpoint

The internal Keycloak adapter connects browser-bound state and PKCE to staff
session issuance with a pinned token exchange. See commercial/KEYCLOAK_STAFF.md.
**32 core, 15 identity and 120 PostgreSQL/HTTP tests pass** using fictional
provider responses. The unchanged Chromium test still fails on the environment's
socket restriction. Next: validate an isolated realm with fictional accounts,
then add browser controls before exposing owner routes. No provider was deployed.

## Latest Keycloak preflight checkpoint

The offline preflight checks an isolated realm's saved metadata and independently
approved signing keys against the exact staff adapter profile. See
commercial/KEYCLOAK_STAFF.md. **32 core, 21 identity and 120 PostgreSQL/HTTP tests
pass**. Keycloak archive download timed out and the unchanged demo Chromium case
still fails on a socket restriction. Next: run the fictional-account browser
matrix against an isolated realm with working Chromium, then wire staff browser
controls. No realm or route was deployed.

## Latest staff expiry cleanup checkpoint

Migration 0011 adds an operator-only function to remove expired staff attempts
and sessions in bounded batches. It skips locked rows and returns counts only.
See commercial/STAFF_AUTH_CLEANUP.md. **32 core, 21 identity and 124 PostgreSQL/HTTP
tests pass**. The unchanged demo Chromium case still fails on a socket
restriction. Next: isolated Keycloak browser qualification, staff browser
controls and wiring a bounded cleanup runner. No job, realm or route was deployed.

## Latest staff browser transport checkpoint

The opt-in qualification app provides staff login, callback, session check
and logout with an exact origin and secure cookies. See commercial/STAFF_BROWSER.md.
**32 core, 21 identity and 130 PostgreSQL/HTTP tests pass** using simulated
provider responses. The unchanged demo Chromium case still fails on a socket
restriction. Next: real isolated realm and Chromium qualification, shared rate
limits, log redaction and expiry runner before owner routes. Nothing deployed.

## Latest staff admission checkpoint

Migration 0012 and an opt-in PostgreSQL hook add shared staff browser limits.
See commercial/STAFF_BROWSER.md. **32 core, 21 identity and 136 PostgreSQL/HTTP
tests pass**. The unchanged demo Chromium case still fails on a socket
restriction. Next: isolated realm and browser qualification, trusted ingress
address and log handling, request deadlines and expiry runner. No deployment.

## Latest staff browser logging checkpoint

The qualification app now emits action/status access events without callback
or cookie credentials. See commercial/STAFF_BROWSER.md. **32 core, 21 identity
and 139 PostgreSQL/HTTP tests pass**. The unchanged demo Chromium case still
fails on a socket restriction. Next: isolated realm and browser qualification,
external log redaction, request deadlines and expiry runner. No deployment.

## Latest staff expiry runner checkpoint

The one-shot staff expiry command calls the restricted PostgreSQL function in
bounded batches and emits counts only. See commercial/STAFF_AUTH_CLEANUP.md.
**32 core, 21 identity and 142 PostgreSQL/HTTP tests pass**. The unchanged demo
Chromium case still fails on a socket restriction. Next: isolated realm and
browser qualification, ingress log redaction and request deadlines, then
rehearse the operator runner before owner routes. No deployment or schedule.

## Latest staff request budget checkpoint

The qualification app now checks a shared cooperative deadline through
admission, connection acquisition, provider exchange and session issuance.
See commercial/STAFF_BROWSER.md. **32 core, 21 identity and 146 PostgreSQL/HTTP
tests pass**. The unchanged Chromium demo case still fails on a socket
restriction. Next: isolated Keycloak/browser qualification, ingress deadline
and log checks, and maintenance rehearsal. No deployment.

## Latest evidence intake checkpoint

Migration 0013 adds tenant/organisation-scoped evidence fingerprints and
concurrent duplicate registration. See commercial/EVIDENCE.md. **32 core,
21 identity and 152 PostgreSQL/HTTP tests pass**. The unchanged demo Chromium
case still fails on a socket restriction. Next: private staged object intake
and quarantine; isolated Keycloak/browser qualification remains a separate
gate before owner routes. No live data or deployment.

## Latest local evidence staging checkpoint

The POSIX spool bounds evidence streams and computes SHA-256 from original bytes.
It keeps bytes in a private temporary file for trusted scanner integration and
closes the handle on context exit. See commercial/EVIDENCE.md. **38 core,
21 identity and 152 PostgreSQL/HTTP tests pass**. The unchanged demo Chromium
case still fails on a socket restriction. Next: tenant-scoped durable
quarantine, retry/orphan cleanup and scan decisions bound to exact stored bytes.
No upload route, scan, extraction or deployment.

## Latest durable evidence quarantine checkpoint

Migration 0014 stores a verified original and receipt atomically in PostgreSQL,
scoped to the tenant and bound to the registration fingerprint and byte count.
Concurrent retries replay the original receipt; the write role cannot read the
payload. See commercial/EVIDENCE.md. **38 core, 21 identity and 158 PostgreSQL/HTTP
tests pass**. The unchanged demo Chromium case still fails on a socket restriction.
Next: scanner-specific access and an exact-byte verdict before any extraction.
No upload route, scanner, extraction, live records or deployment.

## Latest scanner verdict checkpoint

Migration 0015 records exact-byte observations by scanner policy through a
separate worker login. Failures leave no verdict, retries reuse a recorded
result and concurrent disagreements preserve both outcomes with blocked
precedence. See commercial/EVIDENCE.md. **38 core, 21 identity and 163
PostgreSQL/HTTP tests pass**. The unchanged demo browser still fails on a
Chromium socket restriction. Next: durable scan claims and an extraction
gate; no real scanner or extraction is enabled.

## Latest scan claim checkpoint

Migration 0016 gives each evidence/policy scan a recoverable PostgreSQL lease.
Live claims exclude other workers; expired or replaced workers cannot write
verdicts. Completion clears the claim and records the verdict atomically.
**38 core, 21 identity and 166 PostgreSQL/HTTP tests pass**. The unchanged
demo browser fails on Chromium socket permissions. Next: a separate
extraction gate that checks active policy, claim state and exact bytes.
No real scanner, extraction or deployment.

## Latest extraction admission checkpoint

Migration 0017 admits only a tenant/organisation's exact original with a
clean verdict under the operator-configured active policy and no blocking
verdict or live claim. It starts disabled and uses an execute-only login.
**38 core, 21 identity and 169 PostgreSQL/HTTP tests pass**. The unchanged
demo browser fails on Chromium socket permissions. Next: qualify a scanner
and wire isolated extraction with provenance, retry and policy rechecks.

## Latest source-linked CSV extraction checkpoint

The internal CSV reader uses the existing gate and returns exact decimal
candidates with evidence ID, digest, policy and cell coordinates. It keeps
missing, blank and ambiguous values distinct from zero. **42 core,
21 identity and 170 PostgreSQL/HTTP tests pass**. The unchanged demo browser
fails on Chromium socket permissions. Next: persist results with retry
protection and recheck the active policy at write time. No deployment.

## Latest durable CSV extraction checkpoint

Migration 0018 stores source-linked CSV results through a dedicated function
that checks admission again and holds the active policy through commit.
Identical retries return the original receipt. **42 core, 21 identity and
174 PostgreSQL/HTTP tests pass**. The unchanged demo browser fails on
Chromium socket permissions. Next: scoped reads for review and clarification.

## Latest CSV review checkpoint

Migration 0019 adds a scoped, execute-only review read that rechecks source
eligibility and prepares focused questions for unresolved cells. **42 core,
21 identity and 177 PostgreSQL/HTTP tests pass**. The unchanged demo browser
fails on Chromium socket permissions. Next: persist authorised clarification
answers with exact source binding and a write-time eligibility recheck.

## Latest CSV clarification checkpoint

Migration 0020 stores human answers bound to unresolved job cells with a
write-time scanner policy recheck and safe replay. **42 core, 21 identity and
179 PostgreSQL/HTTP tests pass**. The unchanged demo browser fails on
Chromium socket permissions. Next: show answers in review and suppress
resolved prompts without rewriting extraction results.

## Latest answer-aware CSV review checkpoint

Migration 0021 shows attributed answers separately from original candidates
and suppresses only answered prompts. **42 core, 21 identity and 180
PostgreSQL/HTTP tests pass**. The unchanged demo browser fails on Chromium
socket permissions. Next: source-linked draft mapping that refuses missing
amounts and rechecks eligibility before a write.
