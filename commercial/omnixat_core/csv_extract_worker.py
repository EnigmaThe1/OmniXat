"""Explicit bounded extraction into candidates; no HTTP route or ledger effect."""
import argparse
import json
import os
import sys
import psycopg
from .csv_extraction_plan import validate_extraction_plan
from .evidence_extraction_postgres import extract_and_store_csv_amounts, EvidenceNotEligible, CSVExtractionConflict
from .http_api import _pairs
from .private_config import private_file


def main(argv=None):
    parser=argparse.ArgumentParser(description='Extract explicitly selected CSV candidates from eligible quarantine')
    parser.add_argument('--plan-file',required=True)
    args=parser.parse_args(argv)
    try:
        tenant,organisation,evidence,job,selections=validate_extraction_plan(
            json.loads(private_file(args.plan_file),object_pairs_hook=_pairs))
        dsn=private_file(os.environ['OMNIXAT_EXTRACTION_DSN_FILE'])
        with psycopg.connect(dsn,autocommit=True,connect_timeout=5,application_name='omnixat-csv-extractor') as connection:
            receipt=extract_and_store_csv_amounts(connection,tenant,organisation,evidence,job,selections)
        print(json.dumps({'job_id':str(receipt.job_id),'evidence_id':str(receipt.evidence_id),
                          'stored_at':receipt.stored_at.isoformat()}))
        return 0
    except (ValueError,TypeError,KeyError,RecursionError,PermissionError,EvidenceNotEligible,CSVExtractionConflict,psycopg.Error,OSError):
        print('Extraction unavailable; no completed extraction is confirmed. Retry only the same authorised plan.',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
