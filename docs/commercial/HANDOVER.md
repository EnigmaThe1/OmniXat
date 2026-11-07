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
