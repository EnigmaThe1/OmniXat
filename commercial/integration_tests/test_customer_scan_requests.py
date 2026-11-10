"""Durable requests with actual constrained PostgreSQL logins; fictional data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_customer_scan_status import CustomerScanStatusFixture
from test_customer_evidence import SCOPES
from omnixat_core.customer_web import create_app
from omnixat_core.evidence_requests_postgres import request_scan
from omnixat_core.scan_worker import require_requested_scan

REQUEST_SCOPES=SCOPES+' evidence:scan'


class CustomerScanRequestFixture(CustomerScanStatusFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.request_role=cls.role+'_requests'; password=uuid4().hex
        cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(
            sql.Identifier(cls.request_role),sql.Literal(password)))
        cls.request_dsn=make_conninfo(cls.admin_dsn,dbname=cls.database,user=cls.request_role,password=password)
        def cleanup():
            cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(cls.request_role)))
            cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(cls.request_role)))
        cls.addClassCleanup(cleanup)
        for role in [cls.request_role,cls.scanner_role]:
            cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_evidence_requests TO {}').format(sql.Identifier(role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_evidence_requests.request_scan(text,text,bigint,uuid,uuid,uuid) TO {}').format(sql.Identifier(cls.request_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_evidence_requests.cancel_scan(text,text,bigint,uuid,uuid,uuid) TO {}').format(sql.Identifier(cls.request_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_evidence_requests.reauthorise_scan(text,text,bigint,uuid,uuid,uuid,timestamptz) TO {}').format(sql.Identifier(cls.request_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_evidence_requests.worker_request(uuid,uuid) TO {}').format(sql.Identifier(cls.scanner_role)))

    def setUp(self):
        super().setUp()
        @contextmanager
        def requests():
            with psycopg.connect(self.request_dsn,autocommit=True,connect_timeout=2) as connection:
                yield connection
        self.request_connections=requests
        self.app=create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,
            evidence_quarantine_dir=self.spool.name,scan_status_connection_factory=self.status_connections,
            scan_request_connection_factory=requests)
        self.client=TestClient(self.app,base_url=self.origin); self.addCleanup(self.client.close)
        self.request_url=self.url+'/'+self.evidence+'/scan-requests'

    def request(self,**kwargs):
        return self.client.post(self.request_url,content=b'{}',
            headers=self.headers(scope=REQUEST_SCOPES)|{'Content-Type':'application/json'}|kwargs)

    def worker_admit(self,policy='fictional-v1'):
        with psycopg.connect(self.scanner_dsn,autocommit=True) as connection:
            require_requested_scan(connection,self.a,self.org,self.evidence,policy)


class CustomerScanRequestTests(CustomerScanRequestFixture):
    def test_durable_retry_policy_change_and_status(self):
        self.policy()
        first=self.request(); self.assertEqual(first.status_code,202,first.text)
        self.assertEqual(self.request().json()['data'],first.json()['data'])
        self.assertEqual(set(first.json()['data']),{'evidence_id','policy_version','requested_at'})
        self.assertEqual(self.rows('evidence_scan_requests'),1)
        self.assertEqual(self.status().json()['data']['status'],'requested')
        self.worker_admit()
        self.verdict('blocked'); self.assertEqual(self.status().json()['data']['status'],'blocked')
        self.policy('fictional-v2'); self.assertEqual(self.status().json()['data']['status'],'awaiting_scan')
        with self.assertRaises(PermissionError): self.worker_admit('fictional-v2')
        self.assertEqual(self.request().json()['data']['policy_version'],'fictional-v2')
        self.assertEqual(self.rows('evidence_scan_requests'),2)
        self.assertEqual(self.rows('evidence_scan_verdicts'),1)

    def test_concurrent_requests_reuse_first_attribution_and_timestamp(self):
        self.policy(); token=self.token(scope=REQUEST_SCOPES)
        def create(_):
            with self.request_connections() as connection:
                return request_scan(connection,self.verifier,token,self.a,self.org,self.evidence)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results=list(executor.map(create,range(4)))
        self.assertTrue(all(row==results[0] for row in results))
        self.assertEqual(self.rows('evidence_scan_requests'),1)
        self.assertEqual(self.owner.execute('SELECT requested_by FROM omnixat.evidence_scan_requests WHERE tenant_id=%s',(self.a,)).fetchone()[0],self.user)

    def test_fresh_scope_role_human_revocation_and_actor_guards(self):
        self.policy()
        self.assertEqual(self.request(**{'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        for scope in [SCOPES, 'records:read evidence:read evidence:scan', 'records:read records:write evidence:scan']:
            self.assertEqual(self.request(**self.headers(scope=scope)).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.request().status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor' WHERE user_id=%s",(self.user,))
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='agent' WHERE id=%s",(self.user,))
        self.assertEqual(self.request().status_code,403)
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='human',tokens_valid_after=%s WHERE id=%s",(self.iat,self.user))
        with self.request_connections() as connection,self.assertRaises(PermissionError):
            request_scan(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence)
        self.assertEqual(self.rows('evidence_scan_requests'),0)

    def test_worker_requires_current_request_and_rechecks_revocation(self):
        self.policy()
        with self.assertRaises(PermissionError): self.worker_admit()
        self.assertEqual(self.request().status_code,202); self.worker_admit()
        with self.assertRaises(PermissionError): self.worker_admit('unqualified-policy')
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        with self.assertRaises(PermissionError): self.worker_admit()
        self.assertEqual(self.rows('evidence_scan_verdicts'),0)

    def test_worker_rechecks_identity_cutoff_and_disabled_identity(self):
        self.policy(); self.assertEqual(self.request().status_code,202); self.worker_admit()
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=%s WHERE id=%s',(self.iat,self.user))
        with self.assertRaises(PermissionError): self.worker_admit()
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=0,disabled_at=now() WHERE id=%s',(self.user,))
        with self.assertRaises(PermissionError): self.worker_admit()

    def test_no_policy_partial_upload_parent_and_cross_tenant(self):
        self.assertEqual(self.request().status_code,409)
        self.policy()
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        for url in [self.request_url.replace(self.a,self.b),self.request_url.replace(str(self.org),str(uuid4()))]:
            response=self.client.post(url,content=b'{}',headers=self.headers(scope=REQUEST_SCOPES)|{'Content-Type':'application/json'})
            self.assertEqual(response.status_code,404)
        self.owner.execute('DELETE FROM omnixat.evidence_quarantine WHERE tenant_id=%s AND evidence_id=%s',(self.a,self.evidence))
        self.assertEqual(self.request().status_code,409)
        self.assertEqual(self.rows('evidence_scan_requests'),0)

    def test_strict_transport_and_separate_execute_only_grants(self):
        self.policy()
        headers=self.headers(scope=REQUEST_SCOPES)|{'Content-Type':'application/json'}
        for body in [b'',b'[]',b'{"policy":"customer"}',b'{ }',b'{}{}']:
            self.assertEqual(self.client.post(self.request_url,content=body,headers=headers).status_code,400)
        for extra in [{'Origin':'https://other.example.test'},{'Idempotency-Key':'arbitrary'},{'Content-Encoding':'gzip'}]:
            self.assertIn(self.request(**extra).status_code,[400,403,415])
        self.assertEqual(self.client.post(self.request_url+'?policy=x',content=b'{}',headers=headers).status_code,400)
        self.assertEqual(self.client.get(self.request_url,headers=headers).status_code,405)
        with self.request_connections() as connection:
            for query in ['SELECT * FROM omnixat.evidence_scan_requests','SELECT original_bytes FROM omnixat.evidence_quarantine',
                          'DELETE FROM omnixat.evidence_scan_verdicts','DELETE FROM omnixat_extraction.active_scan_policy',
                          'SELECT * FROM omnixat_evidence_requests.worker_request(NULL,NULL)']:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): connection.execute(query)
        with self.status_connections() as connection,self.assertRaises(psycopg.errors.InsufficientPrivilege):
            connection.execute('SELECT * FROM omnixat_evidence_requests.request_scan(NULL,NULL,NULL,NULL,NULL,NULL)')
        with self.assertRaises(PermissionError):
            request_scan(self.runtime,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence)

    def test_request_context_cleanup_and_capability_opt_in(self):
        self.policy()
        with self.request_connections() as connection:
            request_scan(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence)
            for key in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(key,)).fetchone()[0],('',None))
        context=self.client.get(self.base+'/context',headers=self.headers(scope=REQUEST_SCOPES)).json()['data']
        self.assertTrue(context['can_request_scan'])
        self.assertFalse(self.client.get(self.base+'/context',headers=self.headers()).json()['data']['can_request_scan'])
        app=create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,evidence_quarantine_dir=self.spool.name)
        with TestClient(app,base_url=self.origin) as client:
            self.assertEqual(client.post(self.request_url,content=b'{}',headers=self.headers()).status_code,404)

    def test_request_and_worker_with_non_bypass_function_owner(self):
        from hashlib import sha256
        from omnixat_core.postgres import MIGRATIONS
        name='request_owner_'+uuid4().hex; database='request_db_'+uuid4().hex; password=uuid4().hex
        self.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(name),sql.Literal(password)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
        self.admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database),sql.Identifier(name)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database,user=name,password=password),autocommit=True) as owner:
            for file in ['0001_tenant_records.sql','0002_identity_memberships.sql','0013_evidence_registrations.sql',
                         '0014_evidence_quarantine.sql','0015_evidence_scan_verdicts.sql','0016_evidence_scan_claims.sql',
                         '0017_evidence_extraction_gate.sql','0064_customer_scan_status.sql','0065_customer_scan_requests.sql','0066_scan_cancellation.sql','0067_scan_reauthorisation.sql']:
                owner.execute((MIGRATIONS/file).read_text())
            owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_evidence_requests TO {},{}').format(sql.Identifier(self.request_role),sql.Identifier(self.scanner_role)))
            owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_evidence_requests.request_scan(text,text,bigint,uuid,uuid,uuid) TO {}').format(sql.Identifier(self.request_role)))
            owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_evidence_requests.cancel_scan(text,text,bigint,uuid,uuid,uuid) TO {}').format(sql.Identifier(self.request_role)))
            owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_evidence_requests.reauthorise_scan(text,text,bigint,uuid,uuid,uuid,timestamptz) TO {}').format(sql.Identifier(self.request_role)))
            owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_evidence_requests.worker_request(uuid,uuid) TO {}').format(sql.Identifier(self.scanner_role)))
        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database),autocommit=True) as admin:
            admin.execute("INSERT INTO omnixat.tenants VALUES (%s,'Fictional request tenant')",(self.a,))
            admin.execute("INSERT INTO omnixat.organisations(tenant_id,id,display_name,created_by) VALUES (%s,%s,'Fictional request organisation','fixture')",(self.a,self.org))
            admin.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,%s,'human')",(self.user,self.issuer,self.subject))
            admin.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,self.user))
            admin.execute("INSERT INTO omnixat.evidence_registrations(tenant_id,id,organisation_id,content_sha256,media_type,byte_size,registered_by) VALUES (%s,%s,%s,%s,'text/csv',%s,'fixture')",(self.a,self.evidence,self.org,sha256(self.original).digest(),len(self.original)))
            admin.execute('INSERT INTO omnixat.evidence_quarantine(tenant_id,evidence_id,original_bytes) VALUES (%s,%s,%s)',(self.a,self.evidence,self.original))
            admin.execute("INSERT INTO omnixat_extraction.active_scan_policy VALUES (true,'fictional-v1')")
        with psycopg.connect(make_conninfo(self.request_dsn,dbname=database),autocommit=True) as connection:
            receipt=request_scan(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence)
            self.assertEqual(receipt['policy_version'],'fictional-v1')
            with self.assertRaises(PermissionError):
                request_scan(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.b,self.org,self.evidence)
        with psycopg.connect(make_conninfo(self.scanner_dsn,dbname=database),autocommit=True) as connection:
            require_requested_scan(connection,self.a,self.org,self.evidence,'fictional-v1')
            with self.assertRaises(PermissionError):
                require_requested_scan(connection,self.b,self.org,self.evidence,'fictional-v1')

        with psycopg.connect(make_conninfo(self.request_dsn,dbname=database),autocommit=True) as connection:
            request_scan(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence,cancel=True)
        with psycopg.connect(make_conninfo(self.scanner_dsn,dbname=database),autocommit=True) as connection:
            with self.assertRaises(PermissionError):
                require_requested_scan(connection,self.a,self.org,self.evidence,'fictional-v1')

        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database),autocommit=True) as admin:
            stamp=admin.execute('SELECT cancelled_at FROM omnixat.evidence_scan_requests').fetchone()[0].isoformat()
        with psycopg.connect(make_conninfo(self.request_dsn,dbname=database),autocommit=True) as connection:
            request_scan(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence,reauthorise_at=stamp)
        with psycopg.connect(make_conninfo(self.scanner_dsn,dbname=database),autocommit=True) as connection:
            require_requested_scan(connection,self.a,self.org,self.evidence,'fictional-v1')
