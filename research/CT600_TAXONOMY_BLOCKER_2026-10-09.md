# Critical source audit: CT600 taxonomy compatibility

**Date:** 9 October 2026

**Evidence:** pinned source `benhuckvale/ct600-filing@896794599c6cdb213a1122eeaa94b071d777229b`.

- `ct600/computation.py`: `CT_YEAR = "2024"`, `CT_VERSION = "2024-01-01"`.
- `ct600/accounts.py`: `FRC_VERSION = "2024-01-01"`.
- `ct600/build.py` accepts caller-supplied totals and emits the supplied numbers using `float(n):.2f`; it is not a tax calculation or accounting tie-out engine.
- `ct600/submit.py` stores submitted XML, including the `clear` authentication value added by `ct600/build.py`. Never use this file-output scheme for real credentials or personal/company information.
- `ct600/submit.py` uses an HMRC-response-provided polling URL without a local host allowlist and interpolates gateway-returned correlation information into an XML polling document. Require explicit trusted-host and well-formed-identifier checks, plus recovery after timeout.
- The `test_ixbrl.py` fixture validates XML tag presence and XML well-formedness, but not financial statement reconciliation or official gateway acceptance. For example, the `FULL` example carries illustrative profit, turnover and staff-cost figures without a trial-balance reconciliation test.

## Government comparison

[HMRC: Taxonomies accepted by HMRC](https://www.gov.uk/government/publications/taxonomies-accepted-by-hm-revenue-and-customs/taxonomies-accepted-by-hmrc) (updated 17 April 2026):

| Taxonomy | Published accounting period end limit |
|---|---|
| Corporation Tax computational 2024 | **31 March 2026** |
| Corporation Tax computational 2025 | To be advised |
| FRC accounts 2024 | **31 March 2027** |
| FRC accounts 2025 and 2026 | To be advised |

Thus 2026-12-31 company period -> **CT computational 2024 expired**, whereas FRC accounts 2024 is still inside its published date window. Changing only the account taxonomy does not solve the CT computation issue.

## Executed regression test

A lightweight, local Python date-window gate in `scripts/evaluation/taxonomy_gate.py` covers the published date window. It is **not** an HMRC filing validator.

Run without network or dependencies:

```bash
cd scripts/evaluation
python3 -m unittest -v test_taxonomy_gate.py
```

**Authoring-environment result, 9 October 2026: 9/9 tests passed** (Python 3.13.5). No official HMRC submission or Arelle test was run.

## Product decision

**CT600 adapter status: NOT ADOPTED.** Keep the 2026 Python code as a research/renderer candidate, but prohibit any real use until:
1. Tax year/current taxonomy selection and official-schema checks replace pinned constants.
2. Verified deterministic computations calculate all figures, never blindly trusting user/LLM values.
3. Independent accounting tie-outs validate P&L, trial balance, net assets/equity, reliefs and amounts payable.
4. Encrypted credentials and acknowledgement handling are isolated from the LLM and repository.
5. Both official local and appropriately authorised real-gateway validation pass for supported periods.

Do not mistake the passing local date-window unit tests for official submission compatibility.
