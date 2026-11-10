"""Explicit trusted single-item worker. Never mounted by the customer application."""
import argparse
import json
import os
import sys
from uuid import UUID

import psycopg
from .clamd_scanner import ClamdScanner
from .evidence_scan_postgres import scan_quarantined_evidence, EvidenceScanError
from .http_api import _pairs
from .postgres import _tenant_transaction
from .private_config import private_file


def require_requested_scan(connection,tenant,organisation,evidence,policy):
    tenant,organisation,evidence=(UUID(str(x)) for x in (tenant,organisation,evidence))
    with _tenant_transaction(connection,tenant,tables_required=('evidence_scan_requests','identities','memberships')):
        row=connection.execute('SELECT policy_version FROM omnixat_evidence_requests.worker_request(%s,%s)',
                               (organisation,evidence)).fetchone()
        if row is None or row[0]!=policy:
            raise PermissionError('Current authorised scan request required')


def main(argv=None):
    parser=argparse.ArgumentParser(description='Scan one operator-authorised quarantined item')
    for name in ('tenant','organisation','evidence'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--requested',action='store_true',help='Require a durable, current-policy human request')
    args=parser.parse_args(argv)
    try:
        configuration=json.loads(private_file(os.environ['OMNIXAT_SCANNER_CONFIG_FILE']),object_pairs_hook=_pairs)
        if not isinstance(configuration,dict) or set(configuration)!={'socket_path','expected_version','policy_version'}:
            raise ValueError('Explicit qualified scanner configuration required')
        scanner=ClamdScanner(configuration['socket_path'],expected_version=configuration['expected_version'])
        dsn=private_file(os.environ['OMNIXAT_SCANNER_DSN_FILE'])
        with psycopg.connect(dsn,autocommit=True,connect_timeout=5,application_name='omnixat-scanner-worker') as connection:
            if args.requested:
                require_requested_scan(connection,args.tenant,args.organisation,args.evidence,configuration['policy_version'])
            receipt=scan_quarantined_evidence(connection,args.tenant,args.organisation,args.evidence,
                policy_version=configuration['policy_version'],scan=scanner)
        print(json.dumps({'evidence_id':str(receipt.evidence_id),'policy_version':receipt.policy_version,
                          'verdict':receipt.verdict,'recorded_at':receipt.recorded_at.isoformat()}))
        return 0
    except (ValueError,TypeError,KeyError,PermissionError,EvidenceScanError,psycopg.Error,OSError):
        print('Scan unavailable; evidence remains quarantined.',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
