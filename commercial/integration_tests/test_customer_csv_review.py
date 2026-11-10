from contextlib import contextmanager
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_customer_scan_status import CustomerScanStatusFixture
from omnixat_core.customer_web import create_app
from omnixat_core.customer_csv_review import read_latest_csv
from omnixat_core.evidence_csv import AmountCell
from omnixat_core.evidence_extraction_postgres import extract_and_store_csv_amounts


class CustomerCSVReviewFixture(CustomerScanStatusFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for label in ['review','extract']:
            role=cls.role+'_'+label; password=uuid4().hex
            setattr(cls,label+'_role',role)
            setattr(cls,label+'_dsn',make_conninfo(cls.admin_dsn,dbname=cls.database,user=role,password=password))
            cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(role),sql.Literal(password)))
            def cleanup(role=role):
                cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_review TO {}').format(sql.Identifier(cls.review_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_customer_review.read_latest_csv(text,text,bigint,uuid,uuid) TO {}').format(sql.Identifier(cls.review_role)))
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_extraction TO {}').format(sql.Identifier(cls.extract_role)))
        for function in ['read_eligible_original(uuid,uuid)','store_csv_result(uuid,uuid,uuid,text,bytea,jsonb)']:
            cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_extraction.'+function+' TO {}').format(sql.Identifier(cls.extract_role)))

    def setUp(self):
        super().setUp()
        @contextmanager
        def reviews():
            with psycopg.connect(self.review_dsn,autocommit=True) as connection: yield connection
        self.review_connections=reviews
        self.app=create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,
            evidence_quarantine_dir=self.spool.name,csv_review_connection_factory=reviews)
        self.client=TestClient(self.app,base_url=self.origin); self.addCleanup(self.client.close)
        self.review_url=self.url+'/'+self.evidence+'/csv-review'
        self.job=uuid4()

    def extract(self,job=None):
        with psycopg.connect(self.extract_dsn,autocommit=True) as connection:
            return extract_and_store_csv_amounts(connection,self.a,self.org,self.evidence,job or self.job,
                (AmountCell('amount',2,2),AmountCell('missing_amount',3,2)))

    def prepare(self):
        self.policy(); self.verdict('clean'); self.extract()

    def review(self,**headers):
        return self.client.get(self.review_url,headers=self.headers()|headers)


class CustomerCSVReviewTests(CustomerCSVReviewFixture):
    def test_candidates_provenance_answers_and_focused_questions(self):
        self.prepare(); response=self.review(); self.assertEqual(response.status_code,200,response.text)
        data=response.json()['data']; self.assertEqual(data['job_id'],str(self.job))
        self.assertEqual(data['amounts'][0],{'field_name':'amount','row':2,'column':2,'status':'found','amount':'12.00'})
        self.assertEqual(data['questions'][0]['reason'],'missing'); self.assertEqual(len(data['content_sha256']),64)
        # Operator fixture supplies a previously recorded answer; HTTP remains read-only.
        self.owner.execute("INSERT INTO omnixat.csv_clarification_answers VALUES (%s,%s,'missing_amount',3,2,NULL,%s,now())",(self.a,self.job,str(self.user)))
        data=self.review().json()['data']; self.assertEqual(data['questions'],[])
        self.assertIsNone(data['answers'][0]['amount']); self.assertEqual(data['answers'][0]['answered_by'],str(self.user))
        self.assertIn('no-store',response.headers['cache-control'])

    def test_policy_blocking_claims_and_missing_results_deny_review(self):
        self.assertEqual(self.review().status_code,404)
        self.prepare(); self.assertEqual(self.review().status_code,200)
        self.owner.execute("INSERT INTO omnixat.evidence_scan_claims VALUES (%s,%s,'fictional-v1',%s,now()+interval '1 minute')",(self.a,self.evidence,uuid4()))
        self.assertEqual(self.review().status_code,404)
        self.owner.execute('DELETE FROM omnixat.evidence_scan_claims WHERE tenant_id=%s',(self.a,))
        self.verdict('blocked'); self.assertEqual(self.review().status_code,404)
        self.policy('fictional-v2'); self.assertEqual(self.review().status_code,404)

    def test_fresh_membership_scope_human_identity_and_tenant_binding(self):
        self.prepare()
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.review().status_code,200)
        self.assertEqual(self.review(**self.headers(scope='records:read')).status_code,403)
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'viewer',NULL)",(self.b,self.user))
        self.assertEqual(self.client.get(self.review_url.replace(self.a,self.b),headers=self.headers()).status_code,404)
        self.assertEqual(self.client.get(self.review_url.replace(str(self.org),str(uuid4())),headers=self.headers()).status_code,404)
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='agent' WHERE id=%s",(self.user,))
        self.assertEqual(self.review().status_code,404)
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='human' WHERE id=%s",(self.user,))
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=%s WHERE id=%s',(self.iat,self.user))
        with self.review_connections() as connection,self.assertRaises(KeyError):
            read_latest_csv(connection,self.verifier,self.token(scope='records:read evidence:read'),self.a,self.org,self.evidence)

    def test_execute_only_privileges_strict_query_and_opt_in(self):
        self.prepare()
        self.assertEqual(self.client.post(self.review_url,headers=self.headers(),json={}).status_code,405)
        self.assertEqual(self.client.get(self.review_url+'?job=chosen',headers=self.headers()).status_code,400)
        with self.review_connections() as connection:
            for query in ['SELECT original_bytes FROM omnixat.evidence_quarantine',
                          'DELETE FROM omnixat.csv_extraction_results',
                          'SELECT * FROM omnixat_extraction.read_eligible_original(NULL,NULL)']:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): connection.execute(query)
        with self.assertRaises(PermissionError):
            read_latest_csv(self.runtime,self.verifier,self.token(scope='records:read evidence:read'),self.a,self.org,self.evidence)
        app=create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,evidence_quarantine_dir=self.spool.name)
        with TestClient(app,base_url=self.origin) as client:
            self.assertEqual(client.get(self.review_url,headers=self.headers()).status_code,404)

    def test_latest_validated_snapshot_and_context_cleanup(self):
        self.prepare(); newer=uuid4(); self.extract(newer)
        self.assertEqual(self.review().json()['data']['job_id'],str(newer))
        with self.review_connections() as connection:
            read_latest_csv(connection,self.verifier,self.token(scope='records:read evidence:read'),self.a,self.org,self.evidence)
            for key in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(key,)).fetchone()[0],('',None))
        self.owner.execute("UPDATE omnixat.csv_extraction_results SET amounts='[{\"field_name\":\"amount\",\"row\":2,\"column\":2,\"status\":\"found\",\"amount\":\"NaN\"}]' WHERE tenant_id=%s AND job_id=%s",(self.a,newer))
        self.assertEqual(self.review().status_code,404)
        with self.review_connections() as connection,self.assertRaises(KeyError):
            read_latest_csv(connection,self.verifier,self.token(scope='records:read evidence:read'),self.a,self.org,self.evidence)
        with self.review_connections() as connection:
            for key in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(key,)).fetchone()[0],('',None))

    def test_read_capability_with_non_bypass_function_owner(self):
        from hashlib import sha256
        from psycopg.types.json import Jsonb
        from omnixat_core.postgres import MIGRATIONS
        name='csv_owner_'+uuid4().hex; database='csv_db_'+uuid4().hex; password=uuid4().hex
        self.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(name),sql.Literal(password)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
        self.admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database),sql.Identifier(name)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database,user=name,password=password),autocommit=True) as owner:
            for prefix in ['0001','0002','0013','0014','0015','0016','0017','0018','0019','0020','0021','0068']:
                owner.execute(next(MIGRATIONS.glob(prefix+'*.sql')).read_text())
            owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_review TO {}').format(sql.Identifier(self.review_role)))
            owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_customer_review.read_latest_csv(text,text,bigint,uuid,uuid) TO {}').format(sql.Identifier(self.review_role)))
        with psycopg.connect(make_conninfo(self.admin_dsn,dbname=database),autocommit=True) as admin:
            admin.execute("INSERT INTO omnixat.tenants VALUES (%s,'Fictional CSV tenant')",(self.a,))
            admin.execute("INSERT INTO omnixat.organisations(tenant_id,id,display_name,created_by) VALUES (%s,%s,'Fictional CSV organisation','fixture')",(self.a,self.org))
            admin.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,%s,'human')",(self.user,self.issuer,self.subject))
            admin.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'viewer',NULL)",(self.a,self.user))
            admin.execute("INSERT INTO omnixat.evidence_registrations(tenant_id,id,organisation_id,content_sha256,media_type,byte_size,registered_by) VALUES (%s,%s,%s,%s,'text/csv',%s,'fixture')",(self.a,self.evidence,self.org,sha256(self.original).digest(),len(self.original)))
            admin.execute('INSERT INTO omnixat.evidence_quarantine(tenant_id,evidence_id,original_bytes) VALUES (%s,%s,%s)',(self.a,self.evidence,self.original))
            admin.execute("INSERT INTO omnixat_extraction.active_scan_policy VALUES (true,'fictional-v1')")
            admin.execute("INSERT INTO omnixat.evidence_scan_verdicts SELECT tenant_id,evidence_id,content_sha256,byte_size,'fictional-v1','clean',now() FROM omnixat.evidence_quarantine")
            admin.execute("INSERT INTO omnixat.csv_extraction_results(tenant_id,job_id,evidence_id,content_sha256,byte_size,policy_version,amounts) SELECT tenant_id,%s,evidence_id,content_sha256,byte_size,'fictional-v1',%s FROM omnixat.evidence_quarantine",(self.job,Jsonb([{'field_name':'amount','row':2,'column':2,'status':'found','amount':'12.00'}])))
        with psycopg.connect(make_conninfo(self.review_dsn,dbname=database),autocommit=True) as connection:
            value=read_latest_csv(connection,self.verifier,self.token(scope='records:read evidence:read'),self.a,self.org,self.evidence)
            self.assertEqual(value['amounts'][0]['amount'],'12.00')
            with self.assertRaises(KeyError):
                read_latest_csv(connection,self.verifier,self.token(scope='records:read evidence:read'),self.b,self.org,self.evidence)
