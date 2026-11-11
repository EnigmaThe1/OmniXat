"""Explicit bounded extraction into candidates; no HTTP route or ledger effect."""
import argparse
import json
import os
import sys
import psycopg
from .csv_extraction_plan import validate_extraction_plan, validate_extraction_batch
from .evidence_extraction_postgres import extract_and_store_csv_amounts, EvidenceNotEligible, CSVExtractionConflict
from .http_api import _pairs
from .private_config import private_file


def requested_batch(connection,plans):
    """Fail fast; committed receipts survive failure and reconcile on retry."""
    plans=validate_extraction_batch(plans)
    yield from _requested_receipts(connection,plans)


def _requested_receipts(connection,plans):
    from .csv_requests_postgres import extract_requested_csv
    for plan in plans:
        yield extract_requested_csv(connection,*plan)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Extract explicitly selected CSV candidates from eligible quarantine')
    selection=parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--plan-file')
    selection.add_argument('--batch-file',help='Private JSON array of one to five recorded customer plans; requires --requested')
    parser.add_argument('--requested',action='store_true',help='Require the exact recorded customer request and dedicated worker grants')
    args=parser.parse_args(argv)
    try:
        document=json.loads(private_file(args.batch_file or args.plan_file),object_pairs_hook=_pairs)
        if args.batch_file:
            if not args.requested:
                raise ValueError('Batches require recorded customer requests')
            plans=validate_extraction_batch(document)
        else:
            plans=(validate_extraction_plan(document),)
        dsn=private_file(os.environ['OMNIXAT_EXTRACTION_DSN_FILE'])
        with psycopg.connect(dsn,autocommit=True,connect_timeout=5,application_name='omnixat-csv-extractor') as connection:
            if args.requested:
                receipts=_requested_receipts(connection,plans)
            else:
                receipts=(extract_and_store_csv_amounts(connection,*plans[0]),)
            for receipt in receipts:
                print(json.dumps({'job_id':str(receipt.job_id),'evidence_id':str(receipt.evidence_id),
                                  'stored_at':receipt.stored_at.isoformat()}),flush=True)
        return 0
    except (ValueError,TypeError,KeyError,RecursionError,PermissionError,EvidenceNotEligible,CSVExtractionConflict,psycopg.Error,OSError):
        print('Extraction unavailable; earlier receipts may be committed. Retry only the same authorised plans.',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
