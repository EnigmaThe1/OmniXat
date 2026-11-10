from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_csv_extract_worker import CSVExtractWorkerFixture
from test_customer_evidence import SCOPES
from omnixat_core.customer_web import create_app
from omnixat_core.csv_requests_postgres import request_csv, extract_requested_csv
from omnixat_core.evidence_extraction_postgres import EvidenceNotEligible

REQUEST_SCOPES=SCOPES+' evidence:extract'
REQUEST_FUNCTION='omnixat_csv_requests.request_csv(text,text,bigint,uuid,uuid,uuid,uuid,jsonb)'
WORKER_FUNCTIONS=['omnixat_csv_requests.worker_request(uuid,uuid,uuid,jsonb)',
                 'omnixat_csv_requests.store_requested_result(uuid,uuid,uuid,jsonb,text,bytea,jsonb)']


class CustomerCSVRequestFixture(CSVExtractWorkerFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for label in ['csv_request','requested_worker']:
            role=cls.role+'_'+label; password=uuid4().hex
            setattr(cls,label+'_role',role); setattr(cls,label+'_dsn',make_conninfo(cls.admin_dsn,dbname=cls.database,user=role,password=password))
            cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(role),sql.Literal(password)))
            def cleanup(role=role):
                cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            cls.addClassCleanup(cleanup)
            cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_csv_requests TO {}').format(sql.Identifier(role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+REQUEST_FUNCTION+' TO {}').format(sql.Identifier(cls.csv_request_role)))
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_extraction TO {}').format(sql.Identifier(cls.requested_worker_role)))
        for function in WORKER_FUNCTIONS+['omnixat_extraction.read_eligible_original(uuid,uuid)']:
            cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+function+' TO {}').format(sql.Identifier(cls.requested_worker_role)))

    def setUp(self):
        super().setUp()
        @contextmanager
        def requests():
            with psycopg.connect(self.csv_request_dsn,autocommit=True) as connection: yield connection
        self.csv_request_connections=requests
        self.app=create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,evidence_quarantine_dir=self.spool.name,
            csv_review_connection_factory=self.review_connections,csv_request_connection_factory=requests)
        self.client=TestClient(self.app,base_url=self.origin); self.addCleanup(self.client.close)
        self.request_url=self.url+'/'+self.evidence+'/csv-requests'
        self.document={'job_id':str(self.job),'selections':self.plan()['selections']}

    def request(self,document=None,headers=None,url=None):
        return self.client.post(url or self.request_url,json=self.document if document is None else document,
            headers=self.headers(scope=REQUEST_SCOPES)|{'X-OmniXat-Expected-Actor':str(self.user)}|(headers or {}))

    def ready(self):
        self.policy(); self.verdict('clean')

    def requested_worker(self,plan=None,dsn=None):
        # Exercise the real CLI with the requested flag while retaining private-file fixtures.
        import omnixat_core.csv_extract_worker as worker
        original=worker.main
        with patch('test_csv_extract_worker.main',side_effect=lambda argv:original(argv+['--requested'])):
            return self.run_worker(plan=plan,dsn=dsn or self.requested_worker_dsn)

    def dispatch(self,connection):
        from omnixat_core.csv_extraction_plan import validate_extraction_plan
        return extract_requested_csv(connection,*validate_extraction_plan(self.plan()))


class CustomerCSVRequestTests(CustomerCSVRequestFixture):
    def test_request_retry_explicit_cli_and_customer_candidates(self):
        self.ready(); first=self.request(); self.assertEqual(first.status_code,202,first.text)
        self.assertEqual(self.request().json()['data'],first.json()['data'])
        self.assertEqual(set(first.json()['data']),{'job_id','policy_version','requested_at'})
        self.assertEqual(self.rows('csv_extraction_requests'),1); self.assertEqual(self.rows('csv_extraction_results'),0)
        result=self.requested_worker(); self.assertEqual(result[0],0,result[2])
        self.assertEqual(self.requested_worker()[1],result[1])
        self.assertEqual(self.review().json()['data']['amounts'][0]['amount'],'12.00')
        self.assertEqual(self.rows('csv_extraction_results'),1)

    def test_plan_conflicts_scope_and_actor_continuity(self):
        self.ready(); self.assertEqual(self.request().status_code,202)
        changed=[dict(v) for v in self.document['selections']]; changed[0]['row']=3
        self.assertEqual(self.request(self.document|{'selections':changed}).status_code,409)
        self.assertEqual(self.request(headers={'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        self.assertEqual(self.requested_worker(self.plan()|{'selections':changed})[0],1)
        for scope in [SCOPES,'records:read evidence:read evidence:extract','records:read records:write evidence:extract']:
            self.assertEqual(self.request(headers=self.headers(scope=scope)).status_code,403)
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        for url in [self.request_url.replace(self.a,self.b),self.request_url.replace(str(self.org),str(uuid4()))]:
            self.assertEqual(self.request(url=url).status_code,404)
        self.assertEqual(self.rows('csv_extraction_results'),0)

    def test_request_and_worker_require_current_source_and_authority(self):
        self.assertEqual(self.request().status_code,404); self.ready()
        self.assertEqual(self.request().status_code,202)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.request().status_code,403); self.assertEqual(self.requested_worker()[0],1)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor' WHERE user_id=%s",(self.user,))
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='agent' WHERE id=%s",(self.user,))
        self.assertEqual(self.request().status_code,403); self.assertEqual(self.requested_worker()[0],1)
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='human',tokens_valid_after=%s WHERE id=%s",(self.iat,self.user))
        self.assertEqual(self.requested_worker()[0],1)
        self.owner.execute("UPDATE omnixat.identities SET tokens_valid_after=0 WHERE id=%s",(self.user,))
        self.verdict('blocked'); self.assertEqual(self.requested_worker()[0],1); self.assertEqual(self.request().status_code,404)
        self.policy('fictional-v2'); self.assertEqual(self.requested_worker()[0],1)
        self.assertEqual(self.rows('csv_extraction_results'),0)

    def test_fresh_recheck_before_result_storage(self):
        self.ready(); self.request()
        import omnixat_core.csv_requests_postgres as requests
        original=requests.extract_csv_amounts
        def revoke(*args,**kwargs):
            result=original(*args,**kwargs)
            self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
            return result
        with psycopg.connect(self.requested_worker_dsn,autocommit=True) as connection:
            with patch.object(requests,'extract_csv_amounts',side_effect=revoke),self.assertRaises(EvidenceNotEligible):
                self.dispatch(connection)
        self.assertEqual(self.rows('csv_extraction_results'),0)

    def test_strict_json_cells_limits_and_route_opt_in(self):
        self.ready()
        for change in [{'selections':[]},{'selections':self.document['selections']*17},
                       {'selections':[{'field_name':'amount','row':True,'column':2}]},
                       {'selections':[{'field_name':'amount','row':2,'column':2,'amount':'1'}]},
                       {'job_id':'not-a-uuid'},{'extra':'x'}]:
            self.assertEqual(self.request(self.document|change).status_code,422,change)
        self.assertEqual(self.request(headers={'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.request(url=self.request_url+'?policy=chosen').status_code,400)
        self.assertEqual(self.client.get(self.request_url,headers=self.headers()).status_code,405)
        self.assertEqual(self.client.post(self.request_url,json=self.document,headers=self.headers(scope=REQUEST_SCOPES)).status_code,400)
        app=create_app(verifier=self.verifier,connection_factory=self.records_factory,directory_connection_factory=self.directory_factory,
            public_origin=self.origin,evidence_quarantine_dir=self.spool.name,csv_review_connection_factory=self.review_connections)
        with TestClient(app,base_url=self.origin) as client:
            self.assertEqual(client.post(self.request_url,json=self.document,headers=self.headers()).status_code,404)
        self.assertEqual(self.rows('csv_extraction_requests'),0)
        from omnixat_core.postgres import _tenant_transaction
        from psycopg.types.json import Jsonb
        for cells in [[{'field_name':'amount','row':True,'column':2}], self.document['selections']*2]:
            with self.csv_request_connections() as connection,self.assertRaises(psycopg.errors.InvalidParameterValue):
                with _tenant_transaction(connection,__import__('uuid').UUID(self.a),write=True,tables_required=('csv_extraction_requests',)):
                    connection.execute('SELECT * FROM omnixat_csv_requests.request_csv(%s,%s,%s,%s,%s,%s,%s,%s)',
                        (self.issuer,self.subject,self.iat,self.org,self.evidence,self.job,self.user,Jsonb(cells)))

    def test_concurrent_retries_and_separate_privileges(self):
        self.ready(); token=self.token(scope=REQUEST_SCOPES)
        def save(_):
            with self.csv_request_connections() as connection:
                return request_csv(connection,self.verifier,token,self.a,self.org,self.evidence,self.document,expected_actor=self.user)
        with ThreadPoolExecutor(max_workers=3) as executor: receipts=list(executor.map(save,range(3)))
        self.assertTrue(all(v==receipts[0] for v in receipts)); self.assertEqual(self.rows('csv_extraction_requests'),1)
        for dsn in [self.csv_request_dsn,self.extract_dsn,self.runtime_dsn,self.owner_dsn]:
            self.assertEqual(self.requested_worker(dsn=dsn)[0],1)
        with self.csv_request_connections() as connection:
            for query in ['SELECT * FROM omnixat.csv_extraction_requests','SELECT * FROM omnixat.evidence_quarantine',
                          'SELECT * FROM omnixat_csv_requests.worker_request(NULL,NULL,NULL,NULL)']:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): connection.execute(query)

    def test_non_bypass_function_owner_request_and_worker_chain(self):
        from hashlib import sha256
        from omnixat_core.postgres import MIGRATIONS
        name='request_owner_'+uuid4().hex; database='request_db_'+uuid4().hex; password=uuid4().hex
        self.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(name),sql.Literal(password)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
        self.admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database),sql.Identifier(name)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database,user=name,password=password),autocommit=True) as owner:
            for prefix in ['0001','0002','0013','0014','0015','0016','0017','0018','0019','0020','0021','0070','0071','0072']:
                owner.execute(next(MIGRATIONS.glob(prefix+'*.sql')).read_text())
            for role in [self.csv_request_role,self.requested_worker_role]:
                owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_csv_requests TO {}').format(sql.Identifier(role)))
            owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+REQUEST_FUNCTION+' TO {}').format(sql.Identifier(self.csv_request_role)))
            owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_extraction TO {}').format(sql.Identifier(self.requested_worker_role)))
            for function in WORKER_FUNCTIONS+['omnixat_extraction.read_eligible_original(uuid,uuid)']:
                owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+function+' TO {}').format(sql.Identifier(self.requested_worker_role)))
            owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_csv_requests.cancel_csv(text,text,bigint,uuid,uuid,uuid,uuid) TO {}').format(sql.Identifier(self.csv_request_role)))
            owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_csv_requests.reauthorise_csv(text,text,bigint,uuid,uuid,uuid,uuid,timestamptz,uuid) TO {}').format(sql.Identifier(self.csv_request_role)))
            owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_csv_request_status TO {}').format(sql.Identifier(self.review_role)))
            owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_csv_request_status.read_requests(text,text,bigint,uuid,uuid,uuid) TO {}').format(sql.Identifier(self.review_role)))
        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database),autocommit=True) as admin:
            admin.execute("INSERT INTO omnixat.tenants VALUES (%s,'Fictional request tenant')",(self.a,))
            admin.execute("INSERT INTO omnixat.organisations(tenant_id,id,display_name,created_by) VALUES (%s,%s,'Fictional organisation','fixture')",(self.a,self.org))
            admin.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,%s,'human')",(self.user,self.issuer,self.subject))
            admin.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,self.user))
            admin.execute("INSERT INTO omnixat.evidence_registrations(tenant_id,id,organisation_id,content_sha256,media_type,byte_size,registered_by) VALUES (%s,%s,%s,%s,'text/csv',%s,'fixture')",(self.a,self.evidence,self.org,sha256(self.original).digest(),len(self.original)))
            admin.execute('INSERT INTO omnixat.evidence_quarantine(tenant_id,evidence_id,original_bytes) VALUES (%s,%s,%s)',(self.a,self.evidence,self.original))
            admin.execute("INSERT INTO omnixat_extraction.active_scan_policy VALUES (true,'fictional-v1')")
            admin.execute("INSERT INTO omnixat.evidence_scan_verdicts SELECT tenant_id,evidence_id,content_sha256,byte_size,'fictional-v1','clean',now() FROM omnixat.evidence_quarantine")
        with psycopg.connect(make_conninfo(self.csv_request_dsn,dbname=database),autocommit=True) as connection:
            receipt=request_csv(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence,self.document,expected_actor=self.user)
            self.assertEqual(receipt['job_id'],str(self.job))
        with psycopg.connect(make_conninfo(self.requested_worker_dsn,dbname=database),autocommit=True) as connection:
            self.assertEqual(str(self.dispatch(connection).job_id),str(self.job))
        from omnixat_core.csv_requests_postgres import cancel_csv, extract_requested_csv
        from omnixat_core.csv_request_status import read_requests
        from omnixat_core.csv_extraction_plan import validate_extraction_plan
        from omnixat_core.evidence_extraction_postgres import EvidenceNotEligible
        newer=uuid4(); plan=self.plan()|{'job':str(newer)}
        with psycopg.connect(make_conninfo(self.csv_request_dsn,dbname=database),autocommit=True) as connection:
            request_csv(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence,self.document|{'job_id':str(newer)},expected_actor=self.user)
            cancel_csv(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence,newer,expected_actor=self.user)
        with psycopg.connect(make_conninfo(self.review_dsn,dbname=database),autocommit=True) as connection:
            items=read_requests(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence)['items']
            self.assertEqual(items[0]['state'],'cancelled'); self.assertEqual(items[0]['cancelled_by'],str(self.user))
        with psycopg.connect(make_conninfo(self.requested_worker_dsn,dbname=database),autocommit=True) as connection,self.assertRaises(EvidenceNotEligible):
            extract_requested_csv(connection,*validate_extraction_plan(plan))
        from omnixat_core.csv_requests_postgres import reauthorise_csv
        replacement_job=uuid4()
        with psycopg.connect(make_conninfo(self.csv_request_dsn,dbname=database),autocommit=True) as connection:
            reauthorise_csv(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence,newer,
                {'job_id':str(replacement_job),'cancelled_at':items[0]['cancelled_at']},expected_actor=self.user)
        with psycopg.connect(make_conninfo(self.requested_worker_dsn,dbname=database),autocommit=True) as connection:
            extract_requested_csv(connection,*validate_extraction_plan(self.plan()|{'job':str(replacement_job)}))
        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database),autocommit=True) as admin:
            self.assertEqual(admin.execute('SELECT count(*) FROM omnixat.csv_extraction_results').fetchone()[0],2)

    def test_claim_policy_pinning_existing_result_and_disabled_identity(self):
        self.ready()
        self.owner.execute("INSERT INTO omnixat.evidence_scan_claims VALUES (%s,%s,'fictional-v1',%s,now()+interval '1 minute')",(self.a,self.evidence,uuid4()))
        self.assertEqual(self.request().status_code,404)
        self.owner.execute('DELETE FROM omnixat.evidence_scan_claims WHERE tenant_id=%s',(self.a,))
        self.assertEqual(self.requested_worker()[0],1) # No request yet.
        self.extract(); self.assertEqual(self.request().status_code,409) # Never adopt an operator result.
        self.job=uuid4(); self.document['job_id']=str(self.job)
        self.assertEqual(self.request().status_code,202)
        self.owner.execute('UPDATE omnixat.identities SET disabled_at=now() WHERE id=%s',(self.user,))
        self.assertEqual(self.requested_worker()[0],1)
        self.owner.execute('UPDATE omnixat.identities SET disabled_at=NULL WHERE id=%s',(self.user,))
        self.policy('fictional-v2'); self.verdict('clean','fictional-v2')
        self.assertEqual(self.request().status_code,409); self.assertEqual(self.requested_worker()[0],1)
        self.assertEqual(self.rows('csv_extraction_requests'),1)
