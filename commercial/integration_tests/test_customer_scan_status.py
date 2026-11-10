"""Identity/tenant-scoped metadata capability; fictional verdicts for state tests."""
from contextlib import contextmanager
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_customer_evidence import CustomerEvidenceFixture
from omnixat_core.customer_web import create_app
from omnixat_core.evidence_status_postgres import read_scan_status


class CustomerScanStatusFixture(CustomerEvidenceFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.status_role=cls.role+'_status'; cls.scanner_role=cls.role+'_scanner'
        for role in [cls.status_role,cls.scanner_role]:
            password=uuid4().hex
            cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(role),sql.Literal(password)))
            setattr(cls,'status_dsn' if role==cls.status_role else 'scanner_dsn',make_conninfo(cls.admin_dsn,dbname=cls.database,user=role,password=password))
            def cleanup(role=role):
                cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_evidence_status TO {}').format(sql.Identifier(cls.status_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_evidence_status.read_status(text,text,bigint,uuid,uuid) TO {}').format(sql.Identifier(cls.status_role)))
        for grant in ['USAGE ON SCHEMA omnixat','SELECT ON omnixat.evidence_registrations,omnixat.evidence_quarantine,omnixat.evidence_scan_verdicts',
                      'SELECT,INSERT,DELETE ON omnixat.evidence_scan_claims','UPDATE (lease_token,expires_at) ON omnixat.evidence_scan_claims',
                      'INSERT (tenant_id,evidence_id,content_sha256,byte_size,policy_version,verdict) ON omnixat.evidence_scan_verdicts']:
            cls.owner.execute(sql.SQL('GRANT '+grant+' TO {}').format(sql.Identifier(cls.scanner_role)))

    def setUp(self):
        super().setUp()
        @contextmanager
        def status_connections():
            with psycopg.connect(self.status_dsn,autocommit=True,connect_timeout=2) as connection: yield connection
        self.status_connections=status_connections
        self.app=create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,
            evidence_quarantine_dir=self.spool.name,scan_status_connection_factory=status_connections)
        self.client=TestClient(self.app,base_url=self.origin); self.addCleanup(self.client.close)
        self.evidence=self.upload().json()['data']['id']
        self.status_url=self.url+'/'+self.evidence+'/scan-status'
        self.owner.execute('DELETE FROM omnixat_extraction.active_scan_policy')

    def policy(self,value='fictional-v1'):
        self.owner.execute('INSERT INTO omnixat_extraction.active_scan_policy VALUES (true,%s) ON CONFLICT(singleton) DO UPDATE SET policy_version=EXCLUDED.policy_version',(value,))

    def verdict(self,value,policy='fictional-v1'):
        self.owner.execute('''INSERT INTO omnixat.evidence_scan_verdicts
            SELECT tenant_id,evidence_id,content_sha256,byte_size,%s,%s,now()
            FROM omnixat.evidence_quarantine WHERE tenant_id=%s AND evidence_id=%s''',(policy,value,self.a,self.evidence))

    def status(self,**kwargs):
        return self.client.get(self.status_url,headers=self.headers(),**kwargs)


class CustomerScanStatusTests(CustomerScanStatusFixture):
    def test_status_states_policy_change_and_blocked_precedence(self):
        self.assertEqual(self.status().json()['data']['status'],'not_configured')
        self.policy(); self.assertEqual(self.status().json()['data']['status'],'awaiting_scan')
        self.verdict('clean'); self.assertEqual(self.status().json()['data']['status'],'scanned')
        self.owner.execute("INSERT INTO omnixat.evidence_scan_claims VALUES (%s,%s,'fictional-v1',%s,now()+interval '60 seconds')",(self.a,self.evidence,uuid4()))
        result=self.status().json()['data']; self.assertEqual(result['status'],'scanning'); self.assertIsNone(result['recorded_at'])
        self.verdict('blocked'); self.assertEqual(self.status().json()['data']['status'],'blocked')
        self.policy('fictional-v2'); self.assertEqual(self.status().json()['data']['status'],'awaiting_scan')

    def test_expired_claim_does_not_hide_current_clean_observation(self):
        self.policy(); self.verdict('clean')
        self.owner.execute("INSERT INTO omnixat.evidence_scan_claims VALUES (%s,%s,'fictional-v1',%s,now()-interval '1 second')",(self.a,self.evidence,uuid4()))
        result=self.status().json()['data']; self.assertEqual(result['status'],'scanned'); self.assertIsNotNone(result['recorded_at'])

    def test_payload_claim_tokens_and_customer_mutations_are_unavailable(self):
        self.policy(); self.verdict('clean')
        response=self.status(); self.assertEqual(response.status_code,200)
        self.assertEqual(set(response.json()['data']),{'evidence_id','policy_version','status','recorded_at'})
        self.assertIn('no-store',response.headers['cache-control'])
        self.assertEqual(self.client.post(self.status_url,headers=self.headers(),json={'verdict':'clean'}).status_code,405)
        with self.status_connections() as connection:
            for query in ['SELECT original_bytes FROM omnixat.evidence_quarantine','SELECT * FROM omnixat.evidence_scan_claims',
                          'DELETE FROM omnixat_extraction.active_scan_policy']:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): connection.execute(query)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.runtime.execute("SELECT * FROM omnixat_evidence_status.read_status('x','y',1,NULL,NULL)")

    def test_scope_role_revocation_token_cutoff_and_other_tenant_fail_closed(self):
        self.policy(); self.verdict('clean')
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.status().status_code,200)
        self.assertEqual(self.client.get(self.status_url,headers=self.headers(scope='records:read')).status_code,403)
        self.assertEqual(self.client.get(self.status_url,headers=self.headers(iat=self.iat-60,exp=self.iat-1)).status_code,401)
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'viewer',NULL)",(self.b,self.user))
        self.assertEqual(self.client.get(self.status_url.replace(self.a,self.b),headers=self.headers()).status_code,404)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.status().status_code,403)
        with self.status_connections() as connection,self.assertRaises(KeyError):
            read_scan_status(connection,self.verifier,self.token(scope='records:read evidence:read'),self.a,self.org,self.evidence)

    def test_capability_rechecks_identity_cutoff_and_clears_transaction_context(self):
        with self.status_connections() as connection:
            read_scan_status(connection,self.verifier,self.token(scope='records:read evidence:read'),self.a,self.org,self.evidence)
            for key in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(key,)).fetchone()[0],('',None))
            self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=%s WHERE id=%s',(self.iat,self.user))
            with self.assertRaises(KeyError):
                read_scan_status(connection,self.verifier,self.token(scope='records:read evidence:read'),self.a,self.org,self.evidence)
        with self.assertRaises(PermissionError):
            read_scan_status(self.runtime,self.verifier,self.token(scope='records:read evidence:read'),self.a,self.org,self.evidence)

    def test_query_and_parent_identifiers_are_strict_and_incomplete_upload_is_reported(self):
        for query in ['?policy_version=chosen-by-client','?unknown=1']:
            self.assertEqual(self.client.get(self.status_url+query,headers=self.headers()).status_code,400)
        self.assertEqual(self.client.get(self.status_url.replace(str(self.org),str(uuid4())),headers=self.headers()).status_code,404)
        self.owner.execute('DELETE FROM omnixat.evidence_quarantine WHERE tenant_id=%s AND evidence_id=%s',(self.a,self.evidence))
        self.assertEqual(self.status().json()['data']['status'],'upload_incomplete')

    def test_metadata_function_works_with_non_bypass_owner_and_forced_rls(self):
        from omnixat_core.postgres import MIGRATIONS
        from hashlib import sha256
        name='status_owner_'+uuid4().hex; database='status_db_'+uuid4().hex; password=uuid4().hex
        self.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(name),sql.Literal(password)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
        self.admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database),sql.Identifier(name)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database,user=name,password=password),autocommit=True) as owner:
            for file in ['0001_tenant_records.sql','0002_identity_memberships.sql','0013_evidence_registrations.sql',
                         '0014_evidence_quarantine.sql','0015_evidence_scan_verdicts.sql','0016_evidence_scan_claims.sql',
                         '0017_evidence_extraction_gate.sql','0064_customer_scan_status.sql','0065_customer_scan_requests.sql']:
                owner.execute((MIGRATIONS/file).read_text())
            owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_evidence_status TO {}').format(sql.Identifier(self.status_role)))
            owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_evidence_status.read_status(text,text,bigint,uuid,uuid) TO {}').format(sql.Identifier(self.status_role)))
        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database),autocommit=True) as admin:
            admin.execute("INSERT INTO omnixat.tenants VALUES (%s,'Fictional status tenant')",(self.a,))
            admin.execute("INSERT INTO omnixat.organisations(tenant_id,id,display_name,created_by) VALUES (%s,%s,'Fictional status organisation','fixture')",(self.a,self.org))
            admin.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,%s,'human')",(self.user,self.issuer,self.subject))
            admin.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'viewer',NULL)",(self.a,self.user))
            admin.execute("INSERT INTO omnixat.evidence_registrations(tenant_id,id,organisation_id,content_sha256,media_type,byte_size,registered_by) VALUES (%s,%s,%s,%s,'text/csv',%s,'fixture')",(self.a,self.evidence,self.org,sha256(self.original).digest(),len(self.original)))
            admin.execute('INSERT INTO omnixat.evidence_quarantine(tenant_id,evidence_id,original_bytes) VALUES (%s,%s,%s)',(self.a,self.evidence,self.original))
            admin.execute("INSERT INTO omnixat_extraction.active_scan_policy VALUES (true,'fictional-v1')")
            admin.execute("INSERT INTO omnixat.evidence_scan_verdicts SELECT tenant_id,evidence_id,content_sha256,byte_size,'fictional-v1','clean',now() FROM omnixat.evidence_quarantine")
        with psycopg.connect(make_conninfo(self.status_dsn,dbname=database),autocommit=True) as connection:
            value=read_scan_status(connection,self.verifier,self.token(scope='records:read evidence:read'),self.a,self.org,self.evidence)
            self.assertEqual(value['status'],'scanned')
            with self.assertRaises(KeyError):
                read_scan_status(connection,self.verifier,self.token(scope='records:read evidence:read'),self.b,self.org,self.evidence)
