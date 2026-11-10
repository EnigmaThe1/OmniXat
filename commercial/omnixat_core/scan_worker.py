"""Explicit trusted single-item worker. Never mounted by the customer application."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys

import psycopg
from .clamd_scanner import ClamdScanner
from .evidence_scan_postgres import scan_quarantined_evidence, EvidenceScanError
from .http_api import _pairs


def private_file(path):
    source=Path(path)
    metadata=source.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid!=os.geteuid() or metadata.st_mode & 0o077:
        raise ValueError('Private service-owned file required')
    with source.open('rb') as stream:
        content=stream.read(65537)
    if not content or len(content)>65536:
        raise ValueError('Bounded configuration required')
    return content.decode('utf-8').strip()


def main(argv=None):
    parser=argparse.ArgumentParser(description='Scan one operator-authorised quarantined item')
    for name in ('tenant','organisation','evidence'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv)
    try:
        configuration=json.loads(private_file(os.environ['OMNIXAT_SCANNER_CONFIG_FILE']),object_pairs_hook=_pairs)
        if not isinstance(configuration,dict) or set(configuration)!={'socket_path','expected_version','policy_version'}:
            raise ValueError('Explicit qualified scanner configuration required')
        scanner=ClamdScanner(configuration['socket_path'],expected_version=configuration['expected_version'])
        dsn=private_file(os.environ['OMNIXAT_SCANNER_DSN_FILE'])
        with psycopg.connect(dsn,autocommit=True,connect_timeout=5,application_name='omnixat-scanner-worker') as connection:
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
