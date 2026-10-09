# Architecture decision 001 — Personal first, commercial later

## Scope

A single-owner, private UK tax-control centre. Separate companies from personal tax years. Personal data remains local. No customer sign-up or commercial billing.

## Boundaries

- **Web:** Next.js 16, React 19, same-origin `/api` rewrite.
- **API:** FastAPI, validated inputs, server-side owner sessions and audit events.
- **Storage:** PostgreSQL persistent Docker volume; SQLAlchemy tables. Alpha uses `create_all`; introduce Alembic migrations before sensitive data.
- **Integrations:** read-only Companies House public API using server-only credentials. Do not scrape government sign-in pages. HMRC adapter not implemented.
- **Calculation:** pure Python standard-deadline functions. Corporation Tax is not calculated. All tax years and HMRC accounting periods require explicit user selection.
- **Security:** local loopback binding; secrets in ignored environment file; do not pass credentials to LLMs.
- **Autonomy:** no AI agents or financial actions enabled in this milestone.

## Due-date provenance

1. `companies_house_public_record`: fields `accounts.next_accounts.due_on` and `confirmation_statement.next_due`. No fallback prediction if missing.
2. `user_declared_standard_rule`: user-confirmed obligation/period plus a standard deadline calculation.
3. A past due date always has status `date_passed_status_unknown`, not `late` or `unfiled`.

The application never infers MTD applicability, bank balance, tax payable, filing completion or annual-account requirements from missing information.

## Production evolution

Separate deterministic accounting/tax computation, append-only ledger, documents with content hashes, rule versions, evidence provenance, reconciliation, HMRC API adapters, submission approvals and acknowledgement tracking. Account for MTD quarterly submissions. Introduce tenant boundaries only if commercial use is approved.
