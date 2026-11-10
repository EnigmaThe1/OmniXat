# Explicit trusted CSV extraction worker

This operator-invoked command connects the existing scan gate and deterministic
CSV extractor to persisted candidates in the customer inspection UI. It starts no
HTTP route or background service and does not infer a financial treatment, approve
anything or post entries. It is a development qualification path, not production
malware/OCR/model qualification or an autonomous customer extraction queue.

Use the separate non-owner, non-superuser, non-BYPASSRLS extraction login described
in [EVIDENCE.md](EVIDENCE.md). Its only schema usage is omnixat_extraction; grant:

```sql
GRANT USAGE ON SCHEMA omnixat_extraction TO csv_extractor;
GRANT EXECUTE ON FUNCTION omnixat_extraction.read_eligible_original(uuid,uuid)
  TO csv_extractor;
GRANT EXECUTE ON FUNCTION omnixat_extraction.store_csv_result(uuid,uuid,uuid,text,bytea,jsonb)
  TO csv_extractor;
```

Do not grant direct omnixat access, policy/verdict administration, review/answer
writes, ledger privileges or approval capabilities. Store the DSN in a private
service-owned regular file, referenced by `OMNIXAT_EXTRACTION_DSN_FILE`. The file
reader rejects symlinks, unsafe permissions, non-regular/oversized/blank files.
Ancestor directories and concurrent inode writes remain operator-controlled.

Create an authorised private JSON plan (mode 0600) with exactly these fields:

```json
{
  "tenant": "TENANT_UUID",
  "organisation": "ORGANISATION_UUID",
  "evidence": "EVIDENCE_UUID",
  "job": "STABLE_JOB_UUID",
  "selections": [{"field_name": "amount", "row": 2, "column": 2}]
}
```

The UUID strings above are placeholders, not an executable plan. Replace them only
in private operator storage; never commit a manifest containing real record IDs.
IDs must be canonical UUID strings. Reuse the same job and exact plan for retry;
a changed plan needs a deliberately assigned new job. The field label and cell
coordinates come from the operator-authorised task; they are not invented from a
model's guess or accepted through a public HTTP parameter. No amount is supplied
in a plan. Unknown/duplicate JSON keys, missing fields, invalid coordinates and
duplicate field names fail before database access.

From commercial, with requirements-http installed:

```bash
python -m omnixat_core.csv_extract_worker --plan-file /private/extraction-plan.json
```

The existing gate requires a matching active policy and exact-byte clean verdict,
with no blocking verdict or live scan claim. Originals are fingerprint/size checked.
The existing CSV parser requires bounded UTF-8 comma-separated input (512 KiB,
5000 logical records, 64 columns, 4096 characters/cell) and 1–32 selected cells.
Coordinates are one-based logical CSV record/column numbers, including headers;
quoted multiline fields are not additional logical records. Exact decimal values
retain their scale; missing/blank/ambiguous cells remain unresolved candidates.
No locale guesses, totals, tax treatment or uncertain posting are introduced.

The stored result is rechecked through the existing policy/source gate at commit.
Retry returns the same durable receipt; conflicting job content does not overwrite
it. Stdout is a minimal job/evidence/time JSON receipt, without original bytes,
financial values or DSN. Failures are generic and nonzero. If an output/connection
fails after commit, retry only the same authorised plan to reconcile the outcome.

[Customer inspection](CSV_REVIEW.md) can then display eligible candidates and
questions. It still cannot submit answers or approve/post a draft. Customer-triggered
extraction requests, identity/delegation checks for their dispatch, qualified OCR/model
adapters, production malware coverage and security/restore remain open.

Qualification uses fictional CSVs and private synthetic ClamAV rules. The additional
scanner test exercises actual daemon streaming, worker CLI persistence and customer
Chromium inspection. It does not prove production signature coverage. Independent
provider/gateway suites remain separate from its gateway stand-in.

Sources checked 10 November 2026: [Python csv documentation](https://docs.python.org/3/library/csv.html).
No dependency, legal rule or financial amount was changed by this worker.
