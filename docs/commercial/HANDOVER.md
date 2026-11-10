# OmniXAT autonomous development handover

## Authorised objective

Build a commercial UK AI accounting and compliance platform: multiple customers,
subscriptions/trials, paid developer API, platform-owner administration, autonomous
document processing/bookkeeping/reconciliation, and consented business bank feeds.
Statutory filing always needs explicit human review and approval of the final package.
The owner explicitly authorised continuing development and commits/pushes to GitHub
on 5 November 2026. This does not authorise paid contracts, production deployment,
customer data publication or statutory submissions.

## Current delivery priority (9 November 2026)

The owner now explicitly prioritises production readiness and a complete functional
website. Finish end-to-end customer and owner journeys connected to the existing
services. Do not default back to isolated worker/backend increments unless they
block the selected journey. The earlier UI deferral no longer applies. Production
claims require actual browser/provider/security/restore evidence, not backend test
counts or placeholder screens. Deployment, billing activation and statutory
submission remain unauthorised.

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

## Latest source-linked accounting draft checkpoint

Migration 0022 stores an exact, eligible CSV draft amount derived from an
extracted cell or attributed clarification. It refuses unresolved amounts
and cannot post to the ledger. **42 core, 21 identity and 182 PostgreSQL/HTTP
tests pass**. The unchanged demo browser fails on Chromium socket permissions.
Next: scoped draft reads and explicit accounting context validation.

## Latest scoped draft amount read checkpoint

Migration 0023 returns an exact eligible draft amount with source provenance
through a dedicated read-only role. **42 core, 21 identity and 184
PostgreSQL/HTTP tests pass**. The unchanged demo browser fails on Chromium
socket permissions. Next: validate explicit accounting context for drafts.

## Latest expense draft preflight checkpoint

The read-only GBP expense preview validates an explicitly selected date and
account against trusted scoped policy and converts eligible source amounts
to pence without rounding. **44 core, 21 identity and 185 PostgreSQL/HTTP tests
pass**. The unchanged demo browser fails on Chromium socket permissions.
Next: persistent accounting periods/account policy and a draft-only write.

## Latest persistent expense preparation policy checkpoint

Migration 0024 adds tenant/organisation accounting periods and expense-account
eligibility. A dedicated read-only preview checks the selected period, account
and source eligibility in one snapshot. **44 core, 21 identity and 187
PostgreSQL/HTTP tests pass**. The unchanged demo browser fails on Chromium
socket permissions. Next: an idempotent expense draft write with fresh evidence
and policy checks held through commit. No posting or deployment.

## Latest transactional expense draft checkpoint

Migration 0025 saves one GBP draft per eligible extraction job and amount
field. It derives exact pence, holds evidence and accounting policy checks
through commit, and replays the same receipt for identical eligible retries.
**44 core, 21 identity and 190 PostgreSQL/HTTP tests pass**. The unchanged
prototype browser test fails on Chromium socket permissions. Next: a scoped
expense draft read with source provenance and current eligibility. No posting.

## Latest scoped expense draft review checkpoint

Migration 0026 reads one scoped receipt with exact CSV provenance and saved
accounting context, rechecking evidence, period and account eligibility.
**44 core, 21 identity and 192 PostgreSQL/HTTP tests pass**. The unchanged
prototype browser test fails on Chromium socket permissions. Next: explicit
payer and funding context for draft preparation. No approval or posting.

## Latest expense funding context checkpoint

Migration 0027 records an explicitly selected payer and business or personal
funding source against one eligible expense draft, with attributed replay.
**44 core, 21 identity and 194 PostgreSQL/HTTP tests pass**. The unchanged
prototype browser fails on Chromium socket permissions. Next: scoped funding
review and counterpart account policy before journal preparation. No posting.

## Latest expense funding review checkpoint

Migration 0028 provides scoped read-only review of an eligible draft's
recorded payer and funding choice, distinguishing missing and disabled
choices. **44 core, 21 identity and 196 PostgreSQL/HTTP tests pass**.
The unchanged prototype browser fails on Chromium socket permissions.
Next: explicit counterpart account policy for journal preparation. No posting.

## Latest counterpart policy and journal preview checkpoint

Migration 0029 checks an explicit counterpart account against the saved
funding source and returns a balanced two-line GBP preview with evidence
provenance. **44 core, 21 identity and 198 PostgreSQL/HTTP tests pass**.
The unchanged prototype browser fails on Chromium socket permissions.
Next: save an idempotent journal draft with commit-time eligibility checks.

## Latest durable expense journal checkpoint

Migration 0030 saves one balanced journal draft per expense with exact
pence and source provenance, locking evidence and policy through commit.
**44 core, 21 identity and 200 PostgreSQL/HTTP tests pass**. The unchanged
prototype browser fails on Chromium socket permissions. Next: scoped
review of saved journal drafts against current eligibility. No posting.

## Latest saved journal review checkpoint

Migration 0031 reads one scoped saved journal, comparing the stored
snapshot against current eligibility and provenance. **44 core,
21 identity and 202 PostgreSQL/HTTP tests pass**. The unchanged prototype
browser fails on Chromium socket permissions. Next: an attributed human
journal review decision bound to the exact snapshot. No posting.

## Latest journal review decision checkpoint

Migration 0032 adds versioned snapshot digests and records attributed
human bookkeeping observations against eligible snapshots. **44 core,
21 identity and 204 PostgreSQL/HTTP tests pass**. The unchanged prototype
browser fails on Chromium socket permissions. Replace the journal reader
grant as described in EVIDENCE.md. Next: scoped decision review. No posting.

## Latest journal decision history checkpoint

Migration 0033 reads a bounded page of attributed decisions for the exact
eligible journal snapshot and excludes older snapshots. **44 core,
21 identity and 206 PostgreSQL/HTTP tests pass**. The unchanged prototype
browser fails on Chromium socket permissions. Next: structured correction
requests linked to changes-requested observations. No posting or approval.

## Latest structured journal correction checkpoint

Migration 0034 attaches a fixed correction reason to an exact
changes-requested observation, with attribution and retry protection.
**44 core, 21 identity and 208 PostgreSQL/HTTP tests pass**. The unchanged
prototype browser fails on Chromium socket permissions. Next: show reasons
in scoped review history. No mutation of journals, approval or posting.

## Latest journal correction history checkpoint

Migration 0035 returns exact-snapshot corrections on the same page as
their decisions. Replace the decision-reader grant as described in EVIDENCE.md.
**44 core, 21 identity and 208 PostgreSQL/HTTP tests pass**. The unchanged
prototype browser fails on Chromium socket permissions. Next: focused prompts
for correction reasons. No journal mutation, approval or posting.

## Latest journal correction questions checkpoint

The scoped decision page provides one fixed, evidence-seeking question per
distinct correction reason returned on that page. **46 core and 21 identity
tests pass**. PostgreSQL integration verification is pending because this
runner could not install psycopg. The prototype ran 19 of 20 tests
successfully, with the browser test blocked by Chromium socket permissions.
Next, rerun PostgreSQL integration tests and add explicit clarification
answers bound to the eligible snapshot and reason.

## Latest journal clarification answer checkpoint

Migration 0036 stores one attributed answer per eligible journal snapshot
and correction reason through a dedicated writer. See EVIDENCE.md for
the grant and retry contract. **46 core, 21 identity and 210 PostgreSQL/HTTP
tests pass**, including the previously pending review-page verification.
The unchanged prototype passes 19 of 20 tests with the known Chromium
socket failure. Next: show answers in scoped review and suppress questions
for answered reasons.

## Latest scoped journal clarification review checkpoint

Migration 0037 shows attributed answers for the visible correction reasons
on an eligible decision page and suppresses questions that have an answer.
Replace the dedicated reader grant as documented in EVIDENCE.md. **46 core,
21 identity and 211 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with the known Chromium socket failure. Next: let an
authorised user link eligible evidence to an answered correction for review.

## Latest journal clarification evidence link checkpoint

Migration 0038 stores one attributed supporting original per answered
reason and eligible journal snapshot. The writer records the exact
fingerprint and scan policy through a dedicated grant. See EVIDENCE.md.
**46 core, 21 identity and 213 PostgreSQL/HTTP tests pass**. The unchanged
prototype passes 19 of 20 tests with the known Chromium socket failure.
Next: show eligible evidence links in the scoped review page.

## Latest journal supporting evidence review checkpoint

Migration 0039 returns supporting evidence receipts and current scan
eligibility on the scoped decision page. Replace the dedicated reader
grant as documented in EVIDENCE.md. Migration 0040 fixes concurrent
decision, correction and clarification retries. **46 core, 21 identity,
213 PostgreSQL/HTTP and 60 repeated concurrency checks pass**. The
unchanged prototype passes 19 of 20 tests with the known Chromium socket
failure. Next: preview a correction from a verified CSV amount.

## Latest journal amount correction preview checkpoint

Migration 0041 previews both balanced GBP lines from one explicitly selected
eligible extracted CSV cell on the linked evidence, with the original amount
and exact provenance. See EVIDENCE.md for the dedicated reader grant.
**46 core, 21 identity and 215 PostgreSQL/HTTP tests pass**. The unchanged
prototype passes 19 of 20 tests with the known Chromium socket failure.
Next: persist a scoped amount-correction proposal for review.

## Latest durable amount-correction proposal checkpoint

Migration 0042 stores one attributed source-derived proposal per journal
snapshot through a dedicated writer grant documented in EVIDENCE.md.
Eligibility is held through commit and identical retries reuse the receipt.
**46 core, 21 identity and 218 PostgreSQL/HTTP tests pass**. The unchanged
prototype passes 19 of 20 tests with the known Chromium socket failure.
Next: scoped saved-proposal review with current eligibility checks.

## Latest saved correction proposal review checkpoint

Migration 0043 reads a saved proposal by receipt ID only while its exact
journal snapshot, source, amounts and accounts still match. It returns the
author and balanced GBP lines with exact provenance. See EVIDENCE.md for
the dedicated reader grant. **46 core, 21 identity and 220 PostgreSQL/HTTP
tests pass**. The unchanged prototype passes 19 of 20 tests with the known
Chromium socket failure. Next: an exact-proposal human review decision.

## Latest exact-proposal review decision checkpoint

Migration 0044 adds versioned proposal digests and attributed human
bookkeeping observations with retry protection. Replace the saved-proposal
reader grant as documented in EVIDENCE.md. **46 core, 21 identity and 222
PostgreSQL/HTTP tests pass**. The unchanged prototype passes 19 of 20
tests with the known Chromium socket failure. Next: scoped decision
history for the exact eligible proposal digest.

## Latest correction proposal decision history checkpoint

Migration 0045 reads bounded decision pages for the exact eligible proposal
digest through a dedicated grant documented in EVIDENCE.md. **46 core,
21 identity and 224 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with the known Chromium socket failure. Next: preview
a replacement draft linked to the exact proposal and reviewed observation.

## Latest reviewed replacement preview checkpoint

Migration 0046 previews a replacement draft from an eligible proposal and
one explicitly selected reviewed observation. It retains original accounting
context and source-linked balanced amounts. See EVIDENCE.md for its grant.
**46 core, 21 identity and 226 PostgreSQL/HTTP tests pass**. The unchanged
prototype passes 19 of 20 tests with the known Chromium socket failure.
Next: persist a linked replacement draft with retry protection.

## Latest durable replacement draft checkpoint

Migration 0047 saves a linked replacement draft with exact proposal, review,
source and accounting provenance through a dedicated writer grant in
EVIDENCE.md. Original records are retained. **46 core, 21 identity and 229
PostgreSQL/HTTP tests pass**. The unchanged prototype passes 19 of 20 tests
with the known Chromium socket failure. Next: scoped saved replacement
review with current eligibility checks.


## Latest saved replacement review checkpoint

Migration 0048 reads a saved replacement by receipt ID with current original,
proposal, selected review and evidence eligibility checks. It returns author,
receipt and balanced source-linked preview. Use the dedicated reader grant in
EVIDENCE.md. **46 core, 21 identity and 231 PostgreSQL/HTTP tests pass**.
The unchanged prototype passes 19 of 20 tests with the Chromium socket
permission failure. Next: an explicit, retry-safe current replacement choice
that preserves original lineage and review history. Shared production web/API
integration and final-package human approval remain open.


## Latest explicit replacement selection checkpoint

Migration 0049 records one attributed replacement choice per original journal,
with exact snapshot/proposal digests and retry protection. The service rechecks
source and review eligibility under locks through commit. Use the dedicated
selector grant in EVIDENCE.md. **46 core, 21 identity and 234 PostgreSQL/HTTP
tests pass**. The unchanged prototype passes 19 of 20 tests, with the Chromium
socket permission failure. This historical choice has draft preparation scope.
Next: a unified current-draft reader resolving the selection with fresh
eligibility checks and original lineage. Posting and final-package approval
remain unfinished.


## Latest unified current journal draft checkpoint

Migration 0050 and the shared current reader resolve an original or explicitly
selected replacement with fresh eligibility and exact digest checks on one
statement snapshot. The result retains original, replacement and selection
attribution, with effective balanced lines and source provenance. Use the dedicated
current-reader grant in EVIDENCE.md. **46 core, 21 identity and 237 PostgreSQL/HTTP
tests pass**. The unchanged prototype passes 19 of 20 tests with the Chromium
socket permission failure. Production transport, posting and final-package
approval remain unfinished.
Next: resume tenant-scoped PostgreSQL agent-job persistence using the existing
SQLite development contract, then connect shared evidence/journal services.


## Latest PostgreSQL agent-job checkpoint

Migration 0051 and `PostgresJobStore` provide tenant-scoped creation, idempotent
replay, reads, database-timed leases and persisted progress. Checkpoints require
the current verified worker and token after acquiring the row lock. Completion
clears the lease. Apply the dedicated role grants in JOBS_POSTGRES.md.
**46 core, 21 identity and 247 PostgreSQL/HTTP tests pass**. The unchanged
prototype passes 19 of 20 tests with the Chromium socket permission failure.
Production qualification, identity wiring and atomic ledger-effect handling remain
unfinished. Next: tenant-authorised PostgreSQL job cancellation with claim and
checkpoint rejection, then effect idempotency before autonomous orchestration.


## Latest PostgreSQL job cancellation checkpoint

Migration 0052 and `PostgresJobStore.cancel` persist first cancellation attribution,
clear leases and preserve progress. Cancel/claim/checkpoint/complete transitions
serialize on the job row. Queued and running preparation can be cancelled through
existing tenant records-write authority. Retries return the original receipt.
**46 core, 21 identity and 255 PostgreSQL/HTTP tests pass**. The unchanged
prototype passes 19 of 20 tests with the Chromium socket permission failure.
Existing role grants cover the migration. See JOBS_POSTGRES.md for semantics and
limits. Next: a fenced transactional preparation effect with an idempotent receipt
and job authority checked together. Production identity/transport qualification
and in-flight external effect controls remain unfinished.


## Latest fenced job note preparation checkpoint

Migration 0053 and `PostgresJobStore.create_note_effect` commit one shared-service
note, audit and job operation receipt under worker/token/lease checks. Recovery
replays the original note and attribution. Changed inputs conflict and cancelled
jobs reject effects. Apply the extra note/receipt grants in JOBS_POSTGRES.md.
**46 core, 21 identity and 262 PostgreSQL/HTTP tests pass**. The unchanged
prototype passes 19 of 20 tests with the Chromium socket permission failure.
This covers local note preparation. Ledger/external effects, current identity
wiring and orchestration remain unfinished. Next: bounded persistent job
retry/failure outcomes and attempt budgets before autonomous worker execution.


## Latest bounded job retry checkpoint

Migration 0054 pins configurable attempt limits, counts claims and records fixed-code
failures with delayed retry or terminal failure. Historical receipt replay preserves
newer claims. Apply the extra failure-table grant in JOBS_POSTGRES.md.
**46 core, 21 identity and 269 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with the Chromium socket permission failure. Default limits
are 3 attempts, configurable 1–20. Existing jobs begin a fresh counted budget at
migration time while preserving their prior state/progress/leases.
Next: validated reference-only task specifications with tenant/organisation binding,
so restarted workers can recover inputs. Current identity wiring, autonomous workers
and provider/ledger integrations remain unfinished.

## Latest recoverable task checkpoint

Migration 0055 and `EvidencePreparationTask` persist exact version-1 reference-only
inputs with tenant/organisation/evidence/fingerprint binding. Typed creation is
atomic with its job and preserves retry attribution and limits. Recovery survives
worker restart/reclaim. Legacy hash-only jobs remain unchanged with no invented
specifications. Apply the additional grants in JOBS_POSTGRES.md.
**46 core, 21 identity and 276 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with Chromium unavailable. Task reads release references
only; current identity, live leases and the existing scan/read gate remain required.
Next: connect a bounded preparation executor to these checks and restart-safe
shared-service effects. Providers, ledger posting and production qualification remain
unfinished. No active implementation remains in this increment.

## Latest authenticated job checkpoint

`AuthenticatedJobStore` uses the shared signed-token/persisted-member lookup before
every typed job operation, including retries and note effects. It caches no tokens
or principals. Separate identity/job roles require the grants in JOBS_POSTGRES.md.
Existing records retain their same-transaction lookup. No migration is needed.
**46 core, 21 identity and 285 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with Chromium unavailable. Revocation is observed on the next
lookup; it does not serialize through an already-admitted job operation.
Next: use recovered references, fresh identity, a live lease and the current evidence
gate for one bounded preparation execution step. No scheduler, provider, UI,
posting or filing integration is wired by this checkpoint. No active implementation
remains in this increment.

## Latest bounded inspection checkpoint

`inspect_preparation_evidence` recovers one task under the current worker lease,
uses the existing policy-gated original read, checks exact source binding and saves
metadata-only inspection progress. Identity/lease are checked again before saving.
Conditional `expected_progress` prevents stale writes replacing a newer checkpoint.
The step leaves the job running and returns no document bytes. No migration is needed.
**46 core, 21 identity and 294 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with Chromium unavailable. See JOBS_POSTGRES.md for dedicated
identity/job/gate grants and the separate-transaction observation boundary.
Next: persist a validated source-specific extraction plan and connect the existing
bounded decimal extractor to a fenced, retry-safe job effect. A saved inspection
is not current eligibility; later work must recheck the gate, identity and lease.
No scheduler, provider, UI, ledger posting or filing is wired. No active
implementation remains in this increment.

## Latest saved CSV plan checkpoint

Migration 0056 and `CSVExtractionPlan` persist one immutable ordered cell plan per
exact evidence task. Saves/replays require fresh identity and current worker/lease,
serialize on the job and preserve first attribution. Read recovery validates the
canonical digest. Apply the plan-table grants in JOBS_POSTGRES.md.
**46 core, 21 identity and 302 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with Chromium unavailable. Saving a plan does not read evidence,
change progress, renew a lease, execute extraction or establish current eligibility.
Next: connect saved plans to the existing decimal reader/current evidence gate and
commit the extraction effect/result receipt under live job fencing. Scheduling,
providers, ledger posting, final approval and production qualification remain open.
No active implementation remains in this increment.

## Future commercial interface direction

The old personal-demo screens are obsolete as a commercial design reference.
A4O is a workflow starting point, not a layout to reproduce. Defer commercial UI
implementation until the owner reviews and decides the design.


## Latest fenced CSV execution checkpoint

Migration 0057 and `execute_preparation_csv` run a saved plan through the current
source gate and bounded decimal reader. An execute-only function locks the job,
checks worker/token/lease, exact source ID/fingerprint and plan, then commits result
and first-worker receipt atomically. Retries preserve original attribution after
reclaim; failures and post-write lease expiry roll back both. Progress is unchanged;
the job stays running. Apply the function grant in JOBS_POSTGRES.md.
**46 core, 21 identity and 312 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with Chromium unavailable. Identity and gate observations are
separate transactions; an admitted call is not revoked retroactively. The last
lease check precedes commit. This trusted worker writer is not a model-facing tool.
Next: recover a job-linked extraction receipt/unresolved-question summary under fresh
identity and evidence eligibility, then connect bounded clarification and expense
preparation. No scheduler, provider, posting, final approval, UI or live integration
is activated. No active implementation remains in this increment.


## Latest job-linked CSV recovery checkpoint

Migration 0058 and `AuthenticatedJobStore.get_csv_summary` recover exact extraction
receipts, source references, counts and pending fixed clarification questions.
The separate execute-only summary login reads current worker/token/lease, plan,
source eligibility and human answers in one stable statement snapshot. Candidate
values are validated then redacted in SQL; this surface returns no monetary values,
original bytes or answer authors. Apply the new grant in JOBS_POSTGRES.md.
**46 core, 21 identity and 320 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with Chromium unavailable. Human answers stop repeated questions;
explicit unavailable answers remain distinct from available amounts. Job progress
is unchanged; no posting or completion decision is implied. Revocation after
identity admission or changes after the read snapshot cannot retract metadata.
Next: persist validated expense-preparation context and connect the existing shared
preparation service using job-scoped retry receipts. Human clarification handoff,
scheduling, providers, posting, final approval and production qualification remain
unfinished. No UI or live integration is activated; no active increment remains.


## Latest saved expense-plan checkpoint

Migration 0059 and `ExpensePreparationPlan` persist explicit GBP/date/period/account
context and an exact saved CSV source cell. Signed methods validate fresh authority;
saves lock the job, check current worker/lease, parent plan and current bookkeeping
configuration, preserve first attribution and roll back failed/expired writes.
Composite task/organisation/period/account references and forced RLS enforce scope.
Apply the append-only plan and read-only configuration grants in JOBS_POSTGRES.md.
**47 core, 21 identity and 328 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with Chromium unavailable. Human preparation uses the shared
input validator without changing its human-only boundary. Historical reads confer
no continuing policy or evidence eligibility; saving neither creates an expense nor
changes progress. Configuration is observed at save time; the final lease check
precedes commit and admitted identity is not retroactively revoked.
Next: execute saved expense plans using a job-fenced shared-service effect with
fresh source/accounting checks and an atomic expense/retry receipt. Human handoff,
scheduling, providers, posting, final approval and production qualification remain
unfinished. No UI/live integration or active increment remains.


## Latest fenced expense execution checkpoint

Migration 0060 and `AuthenticatedJobStore.execute_expense_plan` run saved plans
through existing source-amount and expense creators. No worker-supplied amount is
accepted. Fresh signed identity, live worker/lease, exact plan/source and current
policy checks precede an atomic source-draft/expense/job-receipt transaction.
Recovered-worker retries preserve first attribution and receipt-bound plan digests.
Use the separate execute-only grant in JOBS_POSTGRES.md; human-only preparation
and clarification remain unchanged. The summary guard rejects this write role.
**47 core, 21 identity and 341 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with Chromium unavailable. No progress/completion, funding,
journal, posting or filing approval occurs. Revocation cannot stop already-admitted
transactions; cancellation serializes and preserves earlier committed effects.
The final lease check precedes commit. Next: recover job-linked expense receipts
and review under fresh eligibility, then persist explicit funding/counterpart
intent before journal work. Human handoff, providers, scheduling, posting, final
approval and production qualification remain unfinished. No UI/live integration
or active increment remains.


## Latest expense recovery checkpoint

Migration 0061 and `AuthenticatedJobStore.get_expense_summary` recover original
expense receipts, canonical context and source metadata under current identity,
live worker/lease and existing CSV/expense eligibility gates. A separate execute-only
summary login returns no monetary values or original bytes; SQL checks the exact
job, source, plan digests, context and first-actor attribution before redaction.
Read-only recovery changes no row or progress. Apply grants in JOBS_POSTGRES.md.
**47 core, 21 identity and 349 PostgreSQL/HTTP tests pass**. The unchanged prototype
passes 19 of 20 tests with Chromium unavailable. One statement snapshot covers the
job, source and accounting checks; identity is admitted separately. Later changes
cannot retract metadata and later effects must recheck eligibility. Full human
expense review and statutory approval remain separate. Next: validated explicit
funding/counterpart intent, then job-backed shared journal preparation. Human
handoff, providers, scheduling, posting, final approval and production qualification
remain unfinished. No UI/live integration or active increment remains.

## Latest explicit funding-intent checkpoint (9 November 2026)

Migration 0062 and `AuthenticatedJobStore.save_journal_plan` persist one canonical,
immutable proposed payer/funding/source/counterpart choice for the exact job-backed
expense. Fresh signed authority, both record scopes, live job worker/lease, parent
plan digests, current expense eligibility and exact enabled funding/counterpart
mapping are required. The dedicated execute-only role locks job/configuration rows;
retries preserve first attribution and reject changed intent. Forced RLS and
composite foreign keys bind tenant, organisation, mappings and expense effect.
Historical `get_journal_plan` requires current read authority and checks the saved
plan digest, without claiming current execution eligibility. See JOBS_POSTGRES.md
for grants and snapshot/lease limitations.

**48 core + 21 identity + 358 PostgreSQL/HTTP tests pass (427 commercial total)**.
The unchanged prototype passes 19/20; Chromium is unavailable for its browser case.
No tests were skipped. New tests cover concurrency, rollback on receipt failure and
actual lease expiry, policy/mapping checks, fresh identity after parent recovery,
RLS/composite binding, cancellation/history and unchanged funding/journal/review
rows. Existing human-only funding/journal services remain unchanged; this operation
stores intent only, changes no progress and records no approval.

Next: job-bound shared journal preparation with atomic effect receipts, fresh
source/accounting/funding/claim checks and explicit qualification of agent preparation
authority. Preserve human review, posting and final-package approval boundaries.
Production qualification, providers, scheduling and human handoff remain unfinished.
No UI/live integration or active implementation remains in this increment.

## Latest migration execution checkpoint (9 November 2026)

`migrate` now bounds lock/statement execution with validated operator overrides
and rejects gaps in applied migration history. Existing SQL migrations are unchanged.
Six real PostgreSQL tests cover contention, DDL/receipt rollback, retry, restored
settings and complete schema installation by a constrained database owner.
**48 core + 21 identity + 364 PostgreSQL/HTTP tests pass (433 commercial total)**.
The unchanged demo remains **19/20**, with Chromium launch denied by the host's
socket policy; no test was skipped. See DEVELOPMENT_STATUS.md and POSTGRES.md for
exact commands and scope. This does not qualify restoration, maintained production
server versions, all definer-function execution or launch readiness.

Concurrency: customer-website edits were actively changing in the canonical checkout.
They were left untouched. Migration work used the isolated worktree
`/srv/playground_dev/OmniXat-persistence-20261109` based on `2c19c46`.
Before continuing that website, fetch, inspect its dirty diff and reconcile this
migration commit; never reset/overwrite it. The migration increment itself is complete.

## Latest customer-website checkpoint (9 November 2026)

The commercial website now connects workspace discovery/switching, paginated
organisations and persistent notes to the existing authenticated PostgreSQL
services. It includes permission-aware controls, responsive layouts, loading/error/
empty states, save confirmation/retry and unsaved-note guards. No fake dashboard
figures or inactive feature navigation were added. See CUSTOMER_WEB.md for the
server factory, private configuration, non-root Dockerfile and maintained OIDC
operator-gateway boundary. Provider integration remains to qualify; no password or
token-paste login was added, and browser code never receives a bearer token.

0063 adds subject-scoped directory execution with a dedicated login, owner-only
RLS directory policies and a user/tenant index. Every actual record operation still
checks persisted membership/scopes and tenant isolation. The concurrent migration
commit `5660349` was reviewed and fast-forwarded while preserving website work;
both increments are included in the combined verification.

**48 core + 21 identity + 371 PostgreSQL/HTTP tests pass (440 service total)**.
Supplemental DOM interaction checks against real services passed, including lost
response/retry without duplicate notes. The two real Chromium customer tests are
retained but locally blocked by the host's Unix-socket policy; browser installation
also returned a truncated download. The unchanged prototype remains 19/20 because
its browser case cannot launch. No browser/visual or full-suite-green claim.
Docker is absent locally. CI defines services, real browser, build and prototype
checks; inspect actual results after publication before claiming qualification.

Resume with CI/browser/container failures and exact maintained sign-in/session
qualification, then build the customer evidence-upload/draft-review workflow using
existing services, followed by subscription/owner journeys. Keep focus on the
complete functional website and production acceptance. Current UI is a working
record workflow, not the whole accounting SaaS. Deployment, live billing and all
statutory submissions remain disabled. No active writer remains; the local stash
`69f8a6e` preserves pre-reconciliation edits as a recovery backup only.

CI follow-up: the first run for `b66f082` proved Chromium can run on GitHub and the
unchanged prototype passed 20/20. Administrative test reconnects failed because
Psycopg strips passwords from connection-info DSNs; fixtures now preserve their
original input DSNs. The complete **371 integration tests pass** on a separate
SCRAM-required disposable cluster after this fix. Authentication was not relaxed.
Inspect the follow-up CI for actual customer browser and container results; it also
retains fictional desktop/mobile screenshots. Continue the website priority above.

Supported-runner evidence: [run 42711977745](https://github.com/EnigmaThe1/OmniXat/actions/runs/42711977745)
for `51a1ba8` passed **462 tests** (440 services, 2 real Chromium customer, all 20
unchanged prototype), plus the customer Docker build, on PostgreSQL 16.15. Actual
desktop/mobile screenshots were inspected. A final follow-up adds in-dialog sign-in
recovery after an expired-token 401, fixes the public entry skip target, and adds a
third actual-browser regression and entry/notes screenshots. Check the latest CI
before claiming that extra case passed. Real provider/session qualification and
remaining customer/owner accounting workflows remain the next production work.

The `c05dd6d` CI passed 443 commercial tests (including all 3 actual-browser cases)
and Docker build. One unchanged prototype browser request timed out in that run;
previous CI had passed 20/20. CI now explicitly configures the pinned Playwright
browser through the existing OMNIXAT_CHROMIUM_PATH setting for the prototype too.
No test/assertion/timeout was changed or skipped. Inspect the newest check before
reporting the combined suite result; the timeout cause itself is not established.

## Latest customer evidence intake checkpoint (9 November 2026)

Opt-in customer evidence upload/list connects to the shared staging, registry and
write-only quarantine services. Configure a private spool and narrow grants/scopes
as documented in CUSTOMER_WEB.md; existing deployments/factories keep routes disabled
without that option. The UI shows stored/incomplete upload receipts, same-file retry
and viewer restrictions. No filename/token/bytes enter browser storage. No scanner,
extraction, ledger posting, final approval or live integration was enabled.

**48 core + 21 identity + 383 integration tests pass (452 services total)**, including
12 new real database/HTTP cases. All five retained/new real customer browser tests
were attempted locally and fail at Chromium startup due to host Unix-socket policy;
the unchanged prototype remains 19/20 locally. The preceding remote `6d6ffde` check
passed on the supported CI runner. Inspect the new commit's CI before claiming its
additional upload UI or combined 477-test result passed. No test was skipped.

Work was isolated at `/srv/playground_dev/OmniXat-evidence-20261109`, based on clean
`6d6ffde`; canonical checkout was left untouched. Resume with CI/browser/screenshots,
then exact maintained sign-in and authorised scanner/draft-review qualification.
Private storage/quotas/retention/restore and provider production gates remain open.

Evidence intake is now CI-verified: [run 42717514445](https://github.com/EnigmaThe1/OmniXat/actions/runs/42717514445)
for `7d87fcf` passed **477 tests** (452 service, all 5 real Chromium customer, all 20
unchanged prototype) and the customer container build on PostgreSQL 16.15. The
actual mobile evidence screenshot was inspected for readable receipts/form and
wrapping with no overflow. This supersedes the preceding pending-CI instruction;
local Chromium is still host-blocked. No source/test assertion was changed to bypass
that restriction. No unfinished work or failed CI remains in this increment.
Resume with maintained login/gateway and authorised scanner/draft-review integration;
quarantine, storage/retention/restore, quotas and production qualification gates remain.


## Latest evidence recovery hardening (9 November 2026)

A token expiring between evidence intake and storage now returns sign-in recovery
(401), retaining the exact File/format retry; current-token membership denial stays
403. Conflict/size/format messages explain corrections. **48 core + 21 identity +
384 integration = 453 service tests pass** locally. Two additional real Chromium
cases await CI (seven customer cases total); local browser remains host-blocked.
Base evidence CI passed 477 tests and container build; do not reuse that count as
proof for this follow-up. Read the latest status for commands, concurrency recovery
and limits. Worktree: `/srv/playground_dev/OmniXat-recovery-20261109`, with a preserved
pre-fast-forward stash. No active implementation remains. Resume with CI, maintained
login/session qualification and authorised scanning/draft review; no live operation
or statutory approval is enabled.

## Latest customer evidence receipt checkpoint (10 November 2026)

Customer evidence rows now expose a read-only receipt with the original SHA-256,
declared format, size and registration/storage timestamps. Fresh membership/read
scopes and tenant/organisation/evidence binding protect the opt-in GET/HEAD route;
no original bytes, actor identity or processing capability is exposed. The browser
fetches on expansion and clears on close, with retry/sign-in states and mobile
wrapping. See CUSTOMER_WEB.md and the latest status for configuration and limits.

**48 core + 21 identity + 389 integration = 458 service tests pass** locally on
PostgreSQL 16.15 with UTF8/SCRAM. All nine real customer browser cases were attempted
but blocked before page load by host Unix-socket policy; the unchanged prototype
remains 19/20 locally. No test skipped. Existing CI will exercise both new browser
cases and save a receipt mobile screenshot. Inspect that run and screenshot after
publication before claiming browser/container success. Recovered base `796de6c`
had a successful verify check. No active writer remains after publication.
Next: receipt CI, then maintained login/session and authorised scanning/draft review;
retain quarantine, human approval and the remaining production qualification gates.

## Latest customer session recovery checkpoint (10 November 2026)

Sign-in recovery opens a separate noopener tab, verifies a renewed signed session
and asks the user to return to the original tab. Pending Files/payloads/keys stay
in memory for explicit retry. Browser writes pin the original persisted actor;
409 session_changed preserves pending state if sign-in switches accounts. Normal
identity/membership/scope checks remain required; no header grants authority.
See CUSTOMER_WEB.md and HTTP_API.md. No migration, grant or live provider change.

**48 core + 21 identity + 392 integration = 461 service tests pass** on local
PostgreSQL 16.15 UTF8/SCRAM. All 13 real customer browser cases were attempted
but host-blocked before page load; unchanged prototype is 19/20 locally. Four new
browser regressions and a recovery mobile screenshot must pass CI; no skip or
timeout/assertion weakening. The previous receipt commit c03c05b's CI run
42748219198 actually passed all 487 tests and container build; its receipt mobile
screenshot was visually inspected and closes that prior checkpoint.

Resume with this increment's CI and recovery screenshot, then exact maintained
gateway/provider login, cookie renewal/revocation/logout and authorised scanning/
draft review. Stand-in gateway fixtures do not establish real provider qualification.
Original-tab closure still loses memory-only work. No deployment, billing, filing
or private records were introduced. No active implementation remains after publication.

Recovery CI follow-up: e58d8bc run 42753788667 passed all services and the unchanged
20-test prototype; two of 13 customer browser cases exposed fixture timing and
fulfilled-redirect interception issues (11 passed). Fixtures now await initial
evidence load and explicitly navigate the opened fictional gateway tab to the
actual recovery page. Assertions/timeouts and application code remain intact.
Inspect the follow-up CI; no browser/container success is claimed for that fix yet.

Session recovery is now CI-verified: run 42754414906 for published 5c806e9 passed
**494 tests** (461 services, all 13 real customer Chromium, all 20 unchanged
prototype) and the customer container build. The recovery mobile screenshot was
downloaded and visually inspected for readable instructions and no overflow.
This supersedes the preceding pending-CI instruction and records resolution of
both fixture failures. Application/test code is unchanged by this evidence entry.
No active implementation remains. Resume with exact maintained gateway/provider
login, renewal/revocation/key rotation/logout qualification, then authorised
scanner and customer draft review; fictional gateway fixtures are not a real
provider acceptance result. No deployment, payment activation or filing occurred.

## Latest real customer provider checkpoint (10 November 2026)

An opt-in disposable Keycloak 26.8.2 qualification package now exercises actual
form/code login, S256, strict RFC 9068 token validation and refresh, replay/grant
rejection, and current tenant HTTP/PostgreSQL authority. The official archive is
SHA-256 pinned; CI uses Java 21. Private generated account/client/TLS material
stays in a loopback-only temporary realm and is cleaned up. Production identity
code/schema/grants are unchanged. See KEYCLOAK_CUSTOMER_QUALIFICATION.md.

The minimal provider profile initially lacked access-token sub; an explicit subject
mapper fixes that configuration without relaxing the verifier. **48 core + 21
identity + 392 integration + 5 actual-provider tests = 466 pass** locally on
PostgreSQL 16.15/Java 21.0.13. All 13 customer browser cases remain locally host-
blocked; unchanged prototype is 19/20 locally. No browser test skipped/changed.
Check the published CI for the new provider step plus browser/prototype/container.

This qualifies a narrow real-provider HTTP protocol/service path, not a full
customer identity installation. Resume with CI, then actual OAuth2 Proxy/browser
login, cookie renewal/account switch/logout, key/session revocation and production
MFA/recovery qualification, followed by authorised scanner and draft review. No
provider service was deployed, no real credentials/records were published and no
billing or statutory action occurred. No active implementation remains after publication.

## Latest CI recovery checkpoint (10 November 2026)

f95392d's run 42760709436 timed out in APT browser dependency installation against
the runner's Azure mirror. Services/provider/browser/container were never exercised;
the retained prototype failed with Chromium unavailable. Do not call that run green.
The workflow now uses official HTTPS Ubuntu noble sources on an explicitly guarded
GitHub-hosted Ubuntu 24.04 runner, keeps archive signature verification, bounds APT
retries/timeouts and gives dependency setup an eight-minute budget. No test removed
or weakened, no production dependency/host changed. YAML/all embedded shell syntax,
retained-browser structural checks and 48 core tests passed locally. Inspect the
new CI for actual full qualification, then resume real browser/gateway identity.
No active implementation remains after publication; no deployment/billing/filing.

CI recovery is verified: run 42766550297 for 4e485e6 passed **499 tests** (461
services, 5 actual Keycloak, 13 customer Chromium, 20 unchanged prototype) and the
container build. Official HTTPS Ubuntu sources resolved the setup stall. This
supersedes the pending-CI instructions above and closes real-provider HTTP/service
qualification for this revision. Next is actual browser/gateway session testing;
MFA/recovery and production qualification remain open. This entry changes only
verification documentation; no deployment, billing or filing occurred.

## Latest provider-browser increment (10 November 2026)

Adds two actual Chromium/Keycloak login cases: successful S256/code/nonce/access
validation and wrong-password rejection. The browser uses only the generated
fixture certificate SPKI exception; HTTP TLS verification remains unchanged.
The fixed fictional callback is intercepted, while provider login is real. A shared
fixture completion helper validates tokens. No OAuth2 Proxy/session/MFA qualification
is claimed. CI runs both new cases alongside all prior tests. Compilation, YAML,
diff checks and 48 core tests passed locally; actual provider-browser CI is pending.
Resume from its CI result, then actual gateway cookies/renewal/logout. No deployment,
private records, billing or filing. No active implementation remains after publication.

Provider-browser follow-up: 1086220 CI passed services/native provider/prototype,
but new browser cases found callback navigation and error-selector fixture issues.
Capture the actual callback request with blocked fictional-host DNS and check the
provider's exact rejection text. Follow-up CI is required; no browser success yet.

## Verified provider-browser handover — 10 November 2026

`4ac9eb857a2754af7817d45a3f848ce3b70e0c4e` passed
[CI run 42773047157](https://github.com/EnigmaThe1/OmniXat/actions/runs/42773047157):
**501 tests** (48 core, 21 identity, 392 PostgreSQL integration, five actual
Keycloak HTTP/service, two actual Keycloak Chromium, 13 customer Chromium and all
20 unchanged prototype tests including browser approval), plus customer container
build. This closes the pending provider-browser CI above. The callback request is
captured with fictional-host DNS blocked; callback-page rendering is not required.
The tests retain real provider network/form/code/token checks and strict validation.

Next: actual OAuth2 Proxy/browser cookie issuance, renewal, account switch/logout
against this disposable provider and customer app. Existing customer browser tests
still use a gateway stand-in. MFA/recovery and production qualification remain open.
This documentation-only follow-up records the tested code revision; it changes no
runtime files. Fetch and inspect remote/checkpoint before resuming. No active task
remains after publication; no deployment, billing, contracts or statutory action.

## Actual gateway increment — 10 November 2026

Recovered clean ed78024 and added the explicit OAuth2 Proxy 7.15.6 + Keycloak
loopback customer harness described in commercial/GATEWAY_BROWSER_QUALIFICATION.md.
Two real Chromium cases exercise cookie/login/refresh/local sign-out and permission
boundaries through real ASGI/PostgreSQL. The provider gains an opt-in email profile;
existing strict access-token checks and prior suites remain. Local 48 core and 21
identity tests, compilation and installer syntax pass. Socket binding is denied on
this host, so inspect full CI before claiming gateway/browser success. If CI fails,
resume from the recorded code/diff and correct the actual failure. Next after green:
account switch/pending-work recovery, provider logout/session revocation and MFA.
No deployment, billing, records publication or statutory action.

### Gateway fixture recovery

5b8f7e8 run 42780334595 passed all 461 services, five provider HTTP cases, two
provider Chromium cases and 20 retained prototype tests. New gateway cases failed:
HTTP upstream was rejected by the unchanged HTTPS-required app boundary, then the
next case hit a fixture identity uniqueness conflict. Customer Chromium/container
steps did not run. The fixture now uses real upstream TLS with the generated root
explicitly installed through Go SSL_CERT_FILE and restores the identity after each
case. Landing status/heading checks fail promptly on transport errors. No HTTPS,
issuer, nonce, email, header or database authority validation was relaxed. Also
corrected the operator template refresh from five minutes to one minute, below
the fixture provider's three-minute access-token life. Follow-up CI is required.

50fec20 run 42781089316 passed the real gateway login, attributed record creation,
actual refreshed-token replacement and local sign-out journey. The other test
stopped at a negative-fixture assertion: malformed state is rejected with 500 by
the maintained gateway before its CSRF branch. Use an actual gateway-generated
state, remove the issued CSRF cookie, then require exactly 403 and no session.
This exercises the intended missing-cookie rejection without accepting 500.
All prior services/provider/prototype cases passed again; full follow-up CI remains
required. Checked the pinned gateway's OAuthCallback implementation for this path.

## Verified actual gateway handover — 10 November 2026

`84f6142e7bd5608a8393469c53aa0358724f4b50` passed
[run 42781825221](https://github.com/EnigmaThe1/OmniXat/actions/runs/42781825221):
**503 tests** (48 core, 21 identity, 392 PostgreSQL, five native provider, two
provider Chromium, two actual gateway Chromium, 13 customer Chromium, all 20
retained prototype tests), plus the customer container build. This closes the
pending gateway CI above. See commercial/GATEWAY_BROWSER_QUALIFICATION.md for
setup, sources and limits. Both gateway/provider and gateway/app connections use
verified loopback TLS; no production HTTPS or identity checks were relaxed.
The customer config refresh default is one minute, below the disposable provider's
three-minute token life. Operator session timing still requires qualification.

Next: qualify actual new-tab recovery/pending-file saves and account switching,
then authorised scanner/draft review through the customer website. Other existing
browser tests still use a gateway stand-in; provider logout, server-side cookie
revocation, concurrent refresh, MFA/recovery and production security/restore remain
open. Local socket restrictions persist, but full CI passed the real browser cases.
The final follow-up records evidence and documentation only. Fetch and inspect the
current remote/checkpoint before resuming; no active writer/task remains after
publication. No deployment, paid activation, contracts or statutory action.

## Actual pending-work recovery increment — 10 November 2026

Recovered clean 9dd7ed4; added three real gateway/provider/browser journeys for
new-tab organisation/file recovery and wrong-account note retry. Existing two
gateway cases retain their profile; an opt-in recovery fixture adds a generated
second account, optional evidence scopes and the existing constrained quarantine
fixture. No tokens are fabricated or protocol responses intercepted. Local 48 core
and 21 identity tests, compilation, discovery of five gateway cases and diff checks
passed. TCP loopback binding passed, but local Chromium launch failed with its
process-singleton Unix socket denied; PostgreSQL is absent. Full CI is required. Inspect
CI before claiming success. Provider-cookie removal in the switching fixture does
not qualify provider logout/revocation. Next after green: authorised scanner and
draft-review customer workflows; production MFA/session/security gates remain open.
No deployment, billing, paid contract, private records or statutory action.

### Customer account correction after real recovery proof

2e3cbc8 passed run 42787860362: all 506 tests and container build. Its switching
fixture removed provider cookies to force the form, which does not show how a
customer can correct a silently reused SSO account. The operator gateway template
now requests standard OIDC prompt=login for explicit login/recovery; cookie sessions
and refresh are unchanged. Recovery tests retain provider cookies and require the
real login form, switching to the second account and back using only credentials
and the existing recovery link. No browser-cookie clearing, protocol interception
or fabricated tokens remain in the new tests. Follow-up CI is required for this
configuration change; provider logout/MFA/session revocation are still not claimed.

ef40e80 run 42788896566 retained passing services/native provider/provider browser
and original two gateway/prototype cases. Three recovery cases reached the real
Keycloak reauthentication page but failed looking for an editable username; its
accessibility snapshot shows a locked previous username and Restart login button.
Tests now exercise that actual provider control before entering the account, with
provider cookies retained. Pending-work UI copy explains the account-change/restart
option. No auth rule or assertion is removed, no timeout is extended; follow-up
CI must prove complete recovery and account correction.

Account-correction acceptance also retains the wrong user's still-valid gateway
cookie for the final recovery link: no second manual local sign-out is performed
before restoring the initiating account. This proves the existing link can start
fresh login directly from an authenticated wrong-account session. No runtime rule
is changed by this final test strengthening; follow-up CI remains required.

## Verified pending-work recovery handover — 10 November 2026

`558bb37d0374dcfdee7f528cdafccdb7c9b6e272` passed
[run 42790308992](https://github.com/EnigmaThe1/OmniXat/actions/runs/42790308992):
**506 tests** (48 core, 21 identity, 392 PostgreSQL, five native provider, two
provider Chromium, five gateway Chromium, 13 customer Chromium and all 20 retained
prototype cases), plus customer container build. This supersedes pending notes
above. The three new cases prove original-tab organisation/file recovery and
wrong-account retry rejection/correction through real gateway/provider services.
The template requests prompt=login; the pinned provider exposes Restart login to
change the locked username. The UI explains this option. Direct correction uses
the existing recovery link with the wrong session still valid; no second manual
sign-out, cookie editing, fabricated tokens or protocol interception is required.

Next: authorised scanning/status and draft review through customer evidence UI
and shared quarantine/worker services. No upload is a scan, extraction or ledger
entry. Production MFA/account recovery, provider logout, server-side/copy-cookie
revocation, key rotation, concurrent refresh and security/restore remain open.
Local TCP binding works, but Chromium's Unix socket is denied and PostgreSQL is
absent; full CI passed actual browser/database cases. See the gateway guide for
setup/sources. This final follow-up changes documentation only. Fetch/check remote
before resuming. No active writer/task remains after publication; no deployment,
billing activation, paid contract, private records or statutory action.

## Trusted scanner/status increment — 10 November 2026

Recovered clean a3999b5; latest run 42791352363 passed 506 tests but failed the
container pip download with BrokenPipeError. Implemented private Unix-socket ClamAV
adapter and explicit single-item trusted worker plus migration 0064, separate
execute-only customer status capability, optional server DSN and UI refresh.
No scanner credentials/original read/claim or verdict mutation on the web process.
Eight new offline protocol tests pass (56 core total); 21 identity tests pass.
Seven new PostgreSQL, two Chromium and three actual-daemon qualification tests
await CI. Synthetic test signatures are not production malware protection. Read
commercial/SCANNING.md before resuming; inspect CI, fix actual failures and verify
container build. Next: durable authorised customer scan requests and qualified
extraction/draft review. No deployment, billing, contract, private data or filing.

### Scanner/status CI follow-up

2ba2ce0 run 42797784802 passed 56 core, 21 identity, 399 PostgreSQL tests, all
provider/gateway cases, all three real ClamAV cases and the retained prototype.
Observed official package: clamav-daemon 1.5.4+dfsg-0ubuntu0.24.04.1. The daemon
fixture uses only its private synthetic NDB rule, not the installed official DB.
One customer Chromium case errored after successfully hiding expired-session
content: its role locator excluded the now-hidden status region before checking
empty text. The locator now includes hidden regions so the security assertion
still requires empty DOM content. No production code, auth rule or timeout is
changed; no test skipped. Container build did not run after this error. Inspect
follow-up full CI and build before claiming completion.

### Scanner/status verified checkpoint — 10 November 2026

Code 029189b29a9f0ed470517455f8f5d9b019a1da41 passed the complete commercial
workflow run 42798834630 (job 129770822486): 526 tests, zero failures/errors/skips,
and the customer container build. Exact suite results: 56 core (0.126s),
21 identity (0.314s), 399 PostgreSQL (72.733s), five native Keycloak (37.178s),
two provider Chromium (32.996s), five gateway Chromium (82.995s), three actual
ClamAV worker/status qualification (1.934s), 15 customer Chromium (18.965s), and
all 20 retained fictional-demo tests including browser approval (3.966s).
This supersedes the pending and failed-run notes above. The hidden-region
locator correction preserves the empty-DOM session-expiry assertion.

Qualification used Ubuntu clamav-daemon 1.5.4+dfsg-0ubuntu0.24.04.1 and a private
synthetic NDB rule only. It proves real protocol/worker/persistence/status/UI
behaviour, not production malware coverage. Scanner-browser qualification uses
the existing gateway stand-in; separate real provider/gateway suites also pass.
Production requires qualified immutable scanner configuration/signature policy,
protected socket/credentials and operational security/restore validation.
Uploads remain quarantined; no automatic scan, extraction, ledger entry or final
approval is implied. Scan status is point-in-time and must be rechecked by any
future extraction gate. No customer original is exposed through the status API.

Next resumable scope: durable authorised customer scan requests through shared
services (permissions, policy validation, retry/idempotency and tenant isolation),
then qualified extraction and human draft review. See commercial/SCANNING.md for
configuration, grants and limits. This follow-up changes documentation only.
Fetch/check branch, working tree, remote movement and checks before resuming.
No active writer remains after publication. No deployment, billing activation,
paid contract, private records or statutory submission occurred.

## Durable scan-request implementation checkpoint — 10 November 2026

Implemented migration 0065 and shared request service, strict opt-in POST,
separate execute-only request DSN/capability, customer Request scan UI, requested
status and explicit worker --requested admission. Natural tenant/evidence/policy
idempotency preserves the first receipt/actor, including four concurrent requests.
No client policy, verdict, original download or auto-started scanner. New scope:
evidence:scan plus records:read/write and evidence:read; only current human
owner/editor memberships qualify. The worker checks current policy and requester
revocation/disable/role/token-cutoff before the bounded existing scanner operation.
Read-only status and request credentials stay separate from scanner credentials.

Local verification: 56 core tests passed (0.154s), 21 identity (0.510s), all 408
PostgreSQL integration tests (75.210s) on disposable PostgreSQL 16.2/psycopg 3.3.8,
including nine new request tests, a non-bypass migration owner, tenant isolation,
concurrency, strict transport, grants, actor continuity and revocation/cutoff.
Python compilation, JavaScript syntax and git diff --check passed. An initial
non-bypass test exposed SELECT row locks requiring authority beyond the existing
RLS policies; request admission now uses the established fresh lookup and locks
only the active policy. No identity RLS policy was widened. Member authority is
not continuously locked; the worker independently rechecks it before processing.
Local Chromium download returned invalid/truncated ZIPs; no local browser pass is
claimed. Two new browser cases and the strengthened actual-daemon worker test
await full CI; all prior suites and container/prototype checks remain intact.

Read commercial/SCANNING.md for setup, grants and explicit limits. Requests do not
start an automatic processor. Historical request status is not proof that its
requester remains authorised. Same-policy first-request cancellation/re-authorisation
and bounded dispatch/retry remain the next resumable step, then qualified extraction
and human draft review. Scanner qualification uses synthetic rules; production
malware coverage/configuration/security/restore remain open. Nothing deployed,
billed, contracted, privately disclosed or submitted to an authority.

### Request-browser CI follow-up

b200b24 run 42804900353 passed core/identity/all 408 PostgreSQL tests, actual
provider/gateway and ClamAV suites, 16 of 17 customer browser cases and all 20
retained prototype cases. One new browser case revoked the member immediately
after starting asynchronous status lookup, before Request scan rendered; it then
timed out looking for the button. Added an explicit visible-button barrier before
revoking authority so the case tests denial from a previously authorised screen.
No production code, timeout, permission or security assertion changed. Container
build was skipped after that browser error. Full follow-up CI is still required.

### Verified durable request checkpoint — 10 November 2026

Code ca0ca5e270636c976ee0c8b1fce39b297d034160 passed the full commercial workflow
run 42805866972, job 129794700680: **537 tests**, zero failures/errors/skips and
customer container build. Exact suites: 56 core (0.310s), 21 identity (0.317s),
408 PostgreSQL (66.135s), five native Keycloak (28.873s), two provider Chromium
(24.811s), five gateway Chromium (65.063s), three real ClamAV worker/status
qualification (1.460s), 17 customer Chromium (17.530s), and all 20 retained
prototype tests including browser approval (3.233s). This supersedes pending/failure
notes above. Both new request UI cases pass: persisted status across reload and
fresh rejection after revocation from a previously authorised screen. The actual
daemon test processes an API-created request through explicit --requested worker
admission, stores its verdict and displays the result in Chromium. Browser request
tests use the existing server-side gateway stand-in; independent real provider and
gateway suites also pass. The final synchronization fix changes no runtime rule.

Observed daemon package remains 1.5.4+dfsg-0ubuntu0.24.04.1; qualification uses only
private synthetic signatures and fictional records, not production malware coverage.
No automatic processor, same-policy request cancellation/re-authorisation or
continuous in-flight cancellation is implemented. Next: complete that customer
request lifecycle and bounded dispatch/retry, then qualified extraction/human draft
review through shared services. Read commercial/SCANNING.md for exact grants,
configuration and limits. Production scanner/security/restore qualification remains
open. This final follow-up changes documentation only; runtime matches the passing
CI revision. No active writer remains after publication. Fetch and inspect current
remote/checks before resuming. No deployment, billing activation, contract, private
record publication or statutory submission occurred.

## Scanner configuration descriptor validation — 10 November 2026

Fixed the explicit worker's lstat/open race with a shared stdlib-only private-file
reader. It opens O_NOFOLLOW/O_NONBLOCK/O_CLOEXEC, validates fstat ownership/type/
permissions on that exact descriptor, bounds reads to 65537 bytes, rejects blank
or malformed UTF-8 and closes the descriptor on failure. Seven new tests cover
size boundaries, permissions/owner, symlink, FIFO/directory, pathname replacement
and cleanup. All 63 offline core tests passed locally (0.652s); compilation and
diff checks passed. No database/UI/prototype source changed; full browser/daemon/
container qualification remains pending CI for this revision, with all suites
retained. Python os documentation checked 10 November 2026:
https://docs.python.org/3/library/os.html#os.open

This closes one worker configuration qualification gap, not production scanner
qualification. Ancestor directories and concurrent writes to the same inode must
still be operator-controlled. Next: request cancellation/re-authorisation and
bounded dispatch, then qualified extraction/human review. No active writer remains
after publication. No deployment, payment, contract, private records or filing.

## Bounded requested-scan dispatch checkpoint — 10 November 2026

Added explicit --batch-file worker mode: private operator manifest, one to five
distinct canonical evidence UUIDs, fixed tenant/organisation, full ID validation
before work and mandatory fresh current-request admission for every item. It
emits each committed receipt, stops on the first failure, and retries reuse durable
verdicts from the completed prefix. No background service or automatic retry starts.
Cancellation/re-authorisation, queue enumeration, extraction and ledger remain open.

Local validation: 66 core tests (0.059s), 21 identity (0.294s), and all 411 PostgreSQL
integration tests (48.470s) passed on disposable PostgreSQL 16.2. Three new core
cases cover strict manifests; three new PostgreSQL cases cover partial failure/
retry, revocation between items and validation/admission before scanning. Compilation
and diff checks passed. Existing real-daemon qualification now exercises the batch
CLI with a private single-item manifest; full browser/daemon/container CI for this
revision remains pending. No test was skipped or removed. The preceding 9e5107c
run 42831147525 passed all 544 tests and container build, closing its pending note.

See commercial/SCANNING.md for invocation and limits. The five-item cap is not an
overall wall-clock SLA; per-service timeouts apply. Production scanner qualification
still uses synthetic rules only. Next: customer cancellation/re-authorisation, then
qualified extraction and human draft review. No active writer remains after
publication; no deployment, payment, contract, private records or statutory action.

## Customer scan cancellation checkpoint — 10 November 2026

Implemented migration 0066, separately granted cancel_scan capability, shared
service/strict same-origin POST and customer Cancel scan request action. Retains
original requester and first cancellation attribution/time. Idempotent concurrent
cancellation blocks future requested/batch worker admission; existing verdicts,
claims and originals are preserved. Status prefers observed blocked/scanning/scanned
states before cancelled. Current human owner/editor/scopes and optional initiating
actor are rechecked. No direct table mutation grant or scanner credential on web.

Local verification: 66 core tests (0.102s), 21 identity (0.360s), all 415 PostgreSQL
integration tests (65.679s) on disposable PostgreSQL 16.2 passed, including four
new cancellation cases and strengthened non-BYPASSRLS function-owner coverage.
Python compilation, JavaScript syntax and git diff --check passed. Local Chromium
executable is absent; the new request/cancel/reload/worker-denial browser test and
retained daemon/browser/container/prototype suites await CI. No test removed or
skipped. Prior batch revision 9fef785 full run 42840571777 passed.

Read commercial/SCANNING.md for migration/grant and exact API/behaviour limits.
Cancellation cannot interrupt an already admitted scan or override operator single-
item work. Normal request retries cannot re-authorise a cancelled same-policy
request. Next: explicit re-authorisation with preserved history, then qualified
extraction and human draft review. Production scanner/security/restore gates remain
open; no automatic processing, deployment, billing, contract, private data or filing.
No active writer remains after publication; fetch/check remote before resuming.
