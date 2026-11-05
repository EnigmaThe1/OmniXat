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
