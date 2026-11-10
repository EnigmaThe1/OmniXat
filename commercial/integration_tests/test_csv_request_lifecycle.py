from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from uuid import UUID, uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from starlette.testclient import TestClient
from test_customer_csv_requests import CustomerCSVRequestFixture, REQUEST_SCOPES
from omnixat_core.customer_web import create_app
from omnixat_core.csv_extraction_plan import validate_extraction_plan
from omnixat_core.csv_request_status import read_requests
from omnixat_core.csv_requests_postgres import cancel_csv, CancellationUnavailable
from omnixat_core.evidence_extraction_postgres import EvidenceNotEligible, extract_csv_amounts, _amount_documents
from omnixat_core.postgres import _tenant_transaction

CANCEL_FUNCTION='omnixat_csv_requests.cancel_csv(text,text,bigint,uuid,uuid,uuid,uuid)'
READ_FUNCTION='omnixat_csv_request_status.read_requests(text,text,bigint,uuid,uuid,uuid)'


class CSVRequestLifecycleFixture(CustomerCSVRequestFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lifecycle_role=cls.role+'_lifecycle'; password=uuid4().hex
        cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(cls.lifecycle_role),sql.Literal(password)))
        cls.lifecycle_dsn=make_conninfo(cls.admin_dsn,dbname=cls.database,user=cls.lifecycle_role,password=password)
        def cleanup():
            cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(cls.lifecycle_role)))
            cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(cls.lifecycle_role)))
        cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_csv_request_status TO {}').format(sql.Identifier(cls.lifecycle_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+READ_FUNCTION+' TO {}').format(sql.Identifier(cls.lifecycle_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+CANCEL_FUNCTION+' TO {}').format(sql.Identifier(cls.csv_request_role)))

    def setUp(self):
        super().setUp()
        @contextmanager
        def statuses():
            with psycopg.connect(self.lifecycle_dsn,autocommit=True) as connection: yield connection
        self.lifecycle_connections=statuses
        self.app=create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,evidence_quarantine_dir=self.spool.name,
            csv_review_connection_factory=self.review_connections,csv_request_connection_factory=self.csv_request_connections,
            csv_request_status_connection_factory=statuses)
        self.client=TestClient(self.app,base_url=self.origin); self.addCleanup(self.client.close)

    def listing(self,job=None,headers=None):
        return self.client.get(self.request_url+('/'+str(job) if job else ''),headers=self.headers()|(headers or {}))

    def cancel(self,job=None,headers=None):
        return self.client.post(self.request_url+'/'+str(job or self.job)+'/cancellations',content='{}',
            headers=self.headers(scope=REQUEST_SCOPES)|{'Content-Type':'application/json','X-OmniXat-Expected-Actor':str(self.user)}|(headers or {}))


class CSVRequestLifecycleTests(CSVRequestLifecycleFixture):
    def test_inspect_reload_cancel_retry_and_no_implicit_restart(self):
        self.ready(); self.request()
        first=self.listing(); self.assertEqual(first.status_code,200,first.text)
        data=first.json()['data']; self.assertFalse(data['has_more']); self.assertEqual(data['items'][0]['state'],'awaiting_worker')
        self.assertEqual(data['items'][0]['selections'],self.document['selections'])
        cancelled=self.cancel(); self.assertEqual(cancelled.status_code,202,cancelled.text)
        self.assertEqual(self.cancel().json()['data'],cancelled.json()['data'])
        self.assertEqual(self.request().status_code,202) # Original receipt; never renews cancellation.
        item=self.listing(self.job).json()['data']['items'][0]
        self.assertEqual(item['state'],'cancelled'); self.assertEqual(item['cancelled_by'],str(self.user))
        self.assertEqual(self.requested_worker()[0],1); self.assertEqual(self.rows('csv_extraction_results'),0)
        self.assertIn('no-store',first.headers['cache-control'])

    def test_completed_result_retained_and_cannot_be_cancelled(self):
        self.ready(); self.request(); self.assertEqual(self.requested_worker()[0],0)
        self.assertEqual(self.listing().json()['data']['items'][0]['state'],'result_recorded')
        response=self.cancel(); self.assertEqual(response.status_code,409,response.text)
        self.assertIsNone(self.listing().json()['data']['items'][0]['cancelled_at'])
        self.assertEqual(self.rows('csv_extraction_results'),1)

    def test_cancellation_between_parse_and_storage_blocks_effect(self):
        self.ready(); self.request()
        import omnixat_core.csv_requests_postgres as requests
        original=requests.extract_csv_amounts
        def stop(*args,**kwargs):
            result=original(*args,**kwargs)
            self.assertEqual(self.cancel().status_code,202)
            return result
        with psycopg.connect(self.requested_worker_dsn,autocommit=True) as connection:
            with patch.object(requests,'extract_csv_amounts',side_effect=stop),self.assertRaises(EvidenceNotEligible):
                self.dispatch(connection)
        self.assertEqual(self.rows('csv_extraction_results'),0)

    def test_fresh_human_scope_and_actor_guards_with_viewer_inspection(self):
        self.ready(); self.request()
        self.assertEqual(self.cancel(headers={'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        self.assertEqual(self.cancel(headers=self.headers()).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.listing().status_code,200); self.assertEqual(self.cancel().status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor' WHERE user_id=%s",(self.user,))
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='agent' WHERE id=%s",(self.user,))
        self.assertEqual(self.listing().status_code,403); self.assertEqual(self.cancel().status_code,403)
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='human',tokens_valid_after=%s WHERE id=%s",(self.iat,self.user))
        with self.lifecycle_connections() as connection,self.assertRaises(PermissionError):
            read_requests(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence)

    def test_tenant_parent_payload_and_reader_privileges(self):
        self.ready(); self.request()
        self.assertEqual(self.listing(uuid4()).status_code,404)
        self.assertEqual(self.client.get(self.request_url+'/bad',headers=self.headers()).status_code,400)
        self.assertEqual(self.client.get(self.request_url+'?all=true',headers=self.headers()).status_code,400)
        self.assertEqual(self.cancel(headers={'Origin':'https://other.example'}).status_code,403)
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        for url in [self.request_url.replace(self.a,self.b),self.request_url.replace(str(self.org),str(uuid4()))]:
            self.assertEqual(self.client.get(url,headers=self.headers()).status_code,404)
        with self.lifecycle_connections() as connection:
            for query in ['SELECT * FROM omnixat.csv_extraction_requests','SELECT * FROM omnixat.evidence_quarantine',
                          'SELECT * FROM omnixat_csv_requests.cancel_csv(NULL,NULL,NULL,NULL,NULL,NULL,NULL)']:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): connection.execute(query)
        with self.csv_request_connections() as connection,self.assertRaises(PermissionError):
            read_requests(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence)

    def test_bounded_newest_history_and_direct_job_lookup_after_policy_change(self):
        self.ready(); first=self.job
        for _ in range(22):
            self.request(); self.job=uuid4(); self.document['job_id']=str(self.job)
        self.policy('fictional-v2')
        data=self.listing().json()['data']; self.assertEqual(len(data['items']),20); self.assertTrue(data['has_more'])
        self.assertNotIn(str(first),[x['job_id'] for x in data['items']])
        self.assertEqual(self.listing(first).json()['data']['items'][0]['job_id'],str(first))
        self.assertEqual(self.cancel(first).status_code,202) # Cancellation does not require a still-eligible source.

    def test_store_wins_row_lock_then_cancellation_observes_committed_result(self):
        self.ready(); self.request(); token=self.token(scope=REQUEST_SCOPES)
        started=Event(); name='cancel_'+uuid4().hex
        def cancel_after_store():
            with psycopg.connect(self.csv_request_dsn,autocommit=True,application_name=name) as connection:
                started.set()
                return cancel_csv(connection,self.verifier,token,self.a,self.org,self.evidence,self.job,expected_actor=self.user)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with psycopg.connect(self.requested_worker_dsn,autocommit=True) as worker:
                result=extract_csv_amounts(worker,self.a,self.org,self.evidence,validate_extraction_plan(self.plan())[-1])
                with _tenant_transaction(worker,UUID(self.a),write=True,tables_required=('csv_extraction_requests','csv_extraction_results')):
                    receipt=worker.execute('SELECT * FROM omnixat_csv_requests.store_requested_result(%s,%s,%s,%s,%s,%s,%s)',
                        (self.org,self.evidence,self.job,Jsonb(self.document['selections']),result.policy_version,bytes.fromhex(result.content_sha256),Jsonb(_amount_documents(result)))).fetchone()
                    self.assertEqual(receipt[0],'stored')
                    future=executor.submit(cancel_after_store); self.assertTrue(started.wait(1))
                    deadline=monotonic()+0.8; blocked=False
                    while monotonic()<deadline:
                        blocked=self.owner.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name=%s AND wait_event_type='Lock')",(name,)).fetchone()[0]
                        if blocked: break
                        sleep(0.005)
                    self.assertTrue(blocked,'Cancellation must wait for the requested result transaction')
            with self.assertRaises(CancellationUnavailable): future.result(timeout=3)
        self.assertEqual(self.rows('csv_extraction_results'),1)

    def test_cancel_wins_row_lock_then_waiting_store_rechecks_cancelled_state(self):
        self.ready(); self.request(); name='worker_'+uuid4().hex
        def waiting_worker():
            with psycopg.connect(self.requested_worker_dsn,autocommit=True,application_name=name) as connection:
                return self.dispatch(connection)
        with ThreadPoolExecutor(max_workers=1) as executor:
            with psycopg.connect(self.csv_request_dsn,autocommit=True) as cancelling:
                with _tenant_transaction(cancelling,UUID(self.a),write=True,tables_required=('csv_extraction_requests','identities','memberships')):
                    receipt=cancelling.execute('SELECT * FROM omnixat_csv_requests.cancel_csv(%s,%s,%s,%s,%s,%s,%s)',
                        (self.issuer,self.subject,self.iat,self.org,self.evidence,self.job,self.user)).fetchone()
                    self.assertEqual(receipt[0],'cancelled')
                    future=executor.submit(waiting_worker)
                    deadline=monotonic()+0.8; blocked=False
                    while monotonic()<deadline:
                        blocked=self.owner.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name=%s AND wait_event_type='Lock')",(name,)).fetchone()[0]
                        if blocked: break
                        sleep(0.005)
                    self.assertTrue(blocked,'Requested result must wait for the cancellation transaction')
            with self.assertRaises(EvidenceNotEligible): future.result(timeout=3)
        self.assertEqual(self.rows('csv_extraction_results'),0)
