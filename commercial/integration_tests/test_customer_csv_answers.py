from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_customer_csv_review import CustomerCSVReviewFixture
from test_customer_evidence import SCOPES
from omnixat_core.customer_web import create_app
from omnixat_core.customer_csv_answers import answer_csv

ANSWER_SCOPES=SCOPES+' evidence:clarify'
FUNCTION='omnixat_customer_answers.answer_csv(text,text,bigint,uuid,uuid,uuid,uuid,text,integer,integer,text)'


class CustomerCSVAnswerFixture(CustomerCSVReviewFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.answer_role=cls.role+'_answers'; password=uuid4().hex
        cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(cls.answer_role),sql.Literal(password)))
        cls.answer_dsn=make_conninfo(cls.admin_dsn,dbname=cls.database,user=cls.answer_role,password=password)
        def cleanup():
            cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(cls.answer_role)))
            cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(cls.answer_role)))
        cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_answers TO {}').format(sql.Identifier(cls.answer_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+FUNCTION+' TO {}').format(sql.Identifier(cls.answer_role)))

    def setUp(self):
        super().setUp()
        @contextmanager
        def answers():
            with psycopg.connect(self.answer_dsn,autocommit=True) as connection: yield connection
        self.answer_connections=answers
        self.app=create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,
            evidence_quarantine_dir=self.spool.name,csv_review_connection_factory=self.review_connections,
            csv_answer_connection_factory=answers)
        self.client=TestClient(self.app,base_url=self.origin); self.addCleanup(self.client.close)
        self.answer_url=self.url+'/'+self.evidence+'/csv-answers'
        self.document={'job_id':str(self.job),'field_name':'missing_amount','row':3,'column':2,'amount':'7.500'}

    def answer(self,document=None,headers=None,url=None):
        return self.client.post(url or self.answer_url,json=document if document is not None else self.document,
            headers=self.headers(scope=ANSWER_SCOPES)|{'X-OmniXat-Expected-Actor':str(self.user)}|(headers or {}))


class CustomerCSVAnswerTests(CustomerCSVAnswerFixture):
    def test_exact_answer_attribution_retry_conflict_and_unavailable(self):
        self.prepare(); first=self.answer(); self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(self.answer().json()['data'],first.json()['data'])
        self.assertNotIn('amount',first.json()['data']); self.assertIn('no-store',first.headers['cache-control'])
        self.assertEqual(self.answer(self.document|{'amount':'7.50'}).status_code,409)
        data=self.review().json()['data']; self.assertEqual(data['questions'],[])
        self.assertEqual(data['answers'][0]['amount'],'7.500'); self.assertEqual(data['answers'][0]['answered_by'],str(self.user))
        self.assertEqual(data['amounts'][1]['status'],'missing')
        self.assertEqual(self.rows('csv_clarification_answers'),1)
        self.job=uuid4(); self.extract(); self.document['job_id']=str(self.job); self.document['amount']=None
        self.assertEqual(self.answer().status_code,200)
        self.assertIsNone(self.review().json()['data']['answers'][0]['amount'])

    def test_current_scope_role_identity_cutoff_and_initiating_actor(self):
        self.prepare()
        self.assertEqual(self.answer(headers={'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        for scope in [SCOPES,'records:read evidence:read evidence:clarify','records:read records:write evidence:clarify']:
            self.assertEqual(self.answer(headers=self.headers(scope=scope)).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.answer().status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor' WHERE user_id=%s",(self.user,))
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='agent' WHERE id=%s",(self.user,))
        self.assertEqual(self.answer().status_code,403)
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='human',tokens_valid_after=%s WHERE id=%s",(self.iat,self.user))
        with self.answer_connections() as connection,self.assertRaises(PermissionError):
            answer_csv(connection,self.verifier,self.token(scope=ANSWER_SCOPES),self.a,self.org,self.evidence,self.document,expected_actor=self.user)
        self.assertEqual(self.rows('csv_clarification_answers'),0)

    def test_exact_job_cell_tenant_parent_and_scan_eligibility(self):
        self.prepare()
        for document in [self.document|{'job_id':str(uuid4())},self.document|{'row':2},
                         self.document|{'field_name':'amount','row':2}]:
            self.assertEqual(self.answer(document).status_code,404)
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        for url in [self.answer_url.replace(self.a,self.b),self.answer_url.replace(str(self.org),str(uuid4()))]:
            self.assertEqual(self.answer(url=url).status_code,404)
        self.owner.execute("INSERT INTO omnixat.evidence_scan_claims VALUES (%s,%s,'fictional-v1',%s,now()+interval '1 minute')",(self.a,self.evidence,uuid4()))
        self.assertEqual(self.answer().status_code,404)
        self.owner.execute('DELETE FROM omnixat.evidence_scan_claims WHERE tenant_id=%s',(self.a,))
        self.verdict('blocked'); self.assertEqual(self.answer().status_code,404)
        self.policy('fictional-v2'); self.assertEqual(self.answer().status_code,404)
        self.assertEqual(self.rows('csv_clarification_answers'),0)

    def test_strict_input_origin_query_and_method_boundaries(self):
        self.prepare()
        for change in [{'amount':7.5},{'amount':'NaN'},{'amount':'1,000'},{'amount':''},{'row':True},
                       {'column':65},{'extra':'x'},{'answered_by':'forged'}]:
            self.assertEqual(self.answer(self.document|change).status_code,422,change)
        self.assertEqual(self.answer(headers={'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.answer(url=self.answer_url+'?job=chosen').status_code,400)
        self.assertEqual(self.client.get(self.answer_url,headers=self.headers()).status_code,405)
        headers=self.headers(scope=ANSWER_SCOPES)|{'Content-Type':'application/json','X-OmniXat-Expected-Actor':str(self.user)}
        for body in ['{"amount":null,"amount":"1"}','['*1500+']'*1500]:
            self.assertIn(self.client.post(self.answer_url,content=body,headers=headers).status_code,[400,413])
        self.assertEqual(self.client.post(self.answer_url,json=self.document,headers=self.headers(scope=ANSWER_SCOPES)).status_code,400)
        self.assertEqual(self.rows('csv_clarification_answers'),0)

    def test_concurrent_same_answer_receipt_and_context_cleanup(self):
        self.prepare(); token=self.token(scope=ANSWER_SCOPES)
        def save(_):
            with self.answer_connections() as connection:
                return answer_csv(connection,self.verifier,token,self.a,self.org,self.evidence,self.document,expected_actor=self.user)
        with ThreadPoolExecutor(max_workers=3) as executor: results=list(executor.map(save,range(3)))
        self.assertTrue(all(row==results[0] for row in results)); self.assertEqual(self.rows('csv_clarification_answers'),1)
        with self.answer_connections() as connection:
            answer_csv(connection,self.verifier,token,self.a,self.org,self.evidence,self.document,expected_actor=self.user)
            for key in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(key,)).fetchone()[0],('',None))

    def test_opt_in_and_separate_execute_only_privileges(self):
        self.prepare()
        for dsn in [self.runtime_dsn,self.review_dsn,self.extract_dsn]:
            with psycopg.connect(dsn,autocommit=True) as connection,self.assertRaises(PermissionError):
                answer_csv(connection,self.verifier,self.token(scope=ANSWER_SCOPES),self.a,self.org,self.evidence,self.document,expected_actor=self.user)
        with self.answer_connections() as connection:
            for query in ['SELECT * FROM omnixat.csv_clarification_answers','SELECT * FROM omnixat.evidence_quarantine',
                          'SELECT * FROM omnixat_extraction.read_eligible_original(NULL,NULL)',
                          'SELECT * FROM omnixat_customer_review.read_latest_csv(NULL,NULL,NULL,NULL,NULL)']:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): connection.execute(query)
        app=create_app(verifier=self.verifier,connection_factory=self.records_factory,directory_connection_factory=self.directory_factory,
            public_origin=self.origin,evidence_quarantine_dir=self.spool.name,csv_review_connection_factory=self.review_connections)
        with TestClient(app,base_url=self.origin) as client:
            self.assertEqual(client.post(self.answer_url,json=self.document,headers=self.headers()).status_code,404)

    def test_revoked_disabled_and_expired_identity_cannot_answer(self):
        self.prepare()
        self.assertEqual(self.answer(headers=self.headers(scope=ANSWER_SCOPES,iat=self.iat-60,exp=self.iat-1)).status_code,401)
        self.owner.execute('UPDATE omnixat.identities SET disabled_at=now() WHERE id=%s',(self.user,))
        self.assertEqual(self.answer().status_code,403)
        self.owner.execute('UPDATE omnixat.identities SET disabled_at=NULL WHERE id=%s',(self.user,))
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.answer().status_code,403)
        self.assertEqual(self.rows('csv_clarification_answers'),0)

    def test_non_bypass_function_owner_and_direct_sql_validation(self):
        from hashlib import sha256
        from psycopg.types.json import Jsonb
        from omnixat_core.postgres import MIGRATIONS
        name='answer_owner_'+uuid4().hex; database='answer_db_'+uuid4().hex; password=uuid4().hex
        self.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(name),sql.Literal(password)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
        self.admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database),sql.Identifier(name)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database,user=name,password=password),autocommit=True) as owner:
            for prefix in ['0001','0002','0013','0014','0015','0016','0017','0018','0019','0020','0021','0068','0069']:
                owner.execute(next(MIGRATIONS.glob(prefix+'*.sql')).read_text())
            owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_answers TO {}').format(sql.Identifier(self.answer_role)))
            owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+FUNCTION+' TO {}').format(sql.Identifier(self.answer_role)))
        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database),autocommit=True) as admin:
            admin.execute("INSERT INTO omnixat.tenants VALUES (%s,'Fictional answer tenant')",(self.a,))
            admin.execute("INSERT INTO omnixat.organisations(tenant_id,id,display_name,created_by) VALUES (%s,%s,'Fictional organisation','fixture')",(self.a,self.org))
            admin.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,%s,'human')",(self.user,self.issuer,self.subject))
            admin.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,self.user))
            admin.execute("INSERT INTO omnixat.evidence_registrations(tenant_id,id,organisation_id,content_sha256,media_type,byte_size,registered_by) VALUES (%s,%s,%s,%s,'text/csv',%s,'fixture')",(self.a,self.evidence,self.org,sha256(self.original).digest(),len(self.original)))
            admin.execute('INSERT INTO omnixat.evidence_quarantine(tenant_id,evidence_id,original_bytes) VALUES (%s,%s,%s)',(self.a,self.evidence,self.original))
            admin.execute("INSERT INTO omnixat_extraction.active_scan_policy VALUES (true,'fictional-v1')")
            admin.execute("INSERT INTO omnixat.evidence_scan_verdicts SELECT tenant_id,evidence_id,content_sha256,byte_size,'fictional-v1','clean',now() FROM omnixat.evidence_quarantine")
            admin.execute("INSERT INTO omnixat.csv_extraction_results(tenant_id,job_id,evidence_id,content_sha256,byte_size,policy_version,amounts) SELECT tenant_id,%s,evidence_id,content_sha256,byte_size,'fictional-v1',%s FROM omnixat.evidence_quarantine",(self.job,Jsonb([{'field_name':'missing_amount','row':3,'column':2,'status':'missing','amount':None}])))
        with psycopg.connect(make_conninfo(self.answer_dsn,dbname=database),autocommit=True) as connection:
            receipt=answer_csv(connection,self.verifier,self.token(scope=ANSWER_SCOPES),self.a,self.org,self.evidence,self.document,expected_actor=self.user)
            self.assertEqual(receipt['job_id'],str(self.job))
            from omnixat_core.postgres import _tenant_transaction
            with self.assertRaises(psycopg.errors.InvalidParameterValue):
                with _tenant_transaction(connection,__import__('uuid').UUID(self.a),write=True,tables_required=('csv_clarification_answers',)):
                    connection.execute('SELECT * FROM omnixat_customer_answers.answer_csv(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                        (self.issuer,self.subject,self.iat,self.org,self.evidence,self.job,self.user,'missing_amount',3,2,'NaN'))
