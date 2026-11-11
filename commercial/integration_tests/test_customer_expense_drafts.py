"""Fictional saved preparations, inspected through fresh bearer/SQL authority."""
from contextlib import contextmanager
from datetime import date
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_customer_csv_review import CustomerCSVReviewFixture
from test_customer_evidence import SCOPES
from omnixat_core.access import Principal
from omnixat_core.customer_web import create_app
from omnixat_core.customer_expense_drafts import read_expense_drafts
from omnixat_core.evidence_drafts_postgres import create_csv_draft_amount, create_csv_expense_draft, read_csv_expense_draft
from omnixat_core.evidence_csv import AmountCell
from omnixat_core.expense_context import ExpenseDraftContext

FUNCTION='omnixat_customer_drafts.read_csv_expense_drafts(text,text,bigint,uuid,uuid,uuid)'


class CustomerExpenseDraftFixture(CustomerCSVReviewFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for label in ['draft_review','draft_amount','draft_write','draft_definer']:
            role=cls.role+'_'+label; password=uuid4().hex
            setattr(cls,label+'_role',role)
            setattr(cls,label+'_dsn',make_conninfo(cls.admin_dsn,dbname=cls.database,user=role,password=password))
            cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(role),sql.Literal(password)))
            def cleanup(role=role):
                cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_drafts TO {}').format(sql.Identifier(cls.draft_review_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+FUNCTION+' TO {}').format(sql.Identifier(cls.draft_review_role)))
        for role,function in [(cls.draft_amount_role,'create_csv_draft_amount(uuid,uuid,uuid,text,integer,integer,text)'),
                              (cls.draft_write_role,'create_csv_expense_draft(uuid,uuid,uuid,text,integer,integer,uuid,uuid,date,text,text)')]:
            cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_extraction TO {}').format(sql.Identifier(role)))
            cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_extraction.'+function+' TO {}').format(sql.Identifier(role)))

    def setUp(self):
        super().setUp()
        @contextmanager
        def draft_connections():
            with psycopg.connect(self.draft_review_dsn,autocommit=True) as connection: yield connection
        self.draft_connections=draft_connections
        self.app=self.draft_app()
        self.client=TestClient(self.app,base_url=self.origin); self.addCleanup(self.client.close)
        self.draft_url=self.url+'/'+self.evidence+'/expense-drafts'
        self.period,self.account=uuid4(),uuid4()
        self.actor=Principal(str(self.user),self.a,'editor')  # Explicit interactive qualification fixture only.

    def draft_app(self,enabled=True):
        return create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,
            evidence_quarantine_dir=self.spool.name,
            expense_draft_connection_factory=self.draft_connections if enabled else None)

    def prepare(self):
        self.policy(); self.verdict('clean')
        self.owner.execute("INSERT INTO omnixat.expense_accounting_periods VALUES (%s,%s,%s,'2026-11-01','2026-11-30',true)",(self.a,self.org,self.period))
        self.owner.execute('INSERT INTO omnixat.expense_account_policy VALUES (%s,%s,%s,true)',(self.a,self.org,self.account))
        self.saved=self.add_draft()

    def add_draft(self,job=None):
        job=job or self.job; self.extract(job)
        scope=(self.a,self.org,self.evidence,job,AmountCell('amount',2,2))
        with psycopg.connect(self.draft_amount_dsn,autocommit=True) as connection:
            create_csv_draft_amount(connection,self.actor,*scope)
        with psycopg.connect(self.draft_write_dsn,autocommit=True) as connection:
            return create_csv_expense_draft(connection,self.actor,*scope,
                context=ExpenseDraftContext('GBP',date(2026,11,6),self.account),period_id=self.period)

    def listing(self,draft=None,headers=None,url=None):
        return self.client.get(url or self.draft_url+('/'+str(draft) if draft else ''),headers=self.headers()|(headers or {}))


class CustomerExpenseDraftTests(CustomerExpenseDraftFixture):
    def test_saved_source_amount_context_and_attribution_without_mutation(self):
        self.prepare(); response=self.listing(self.saved.id)
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()['data']; self.assertFalse(data['has_more'])
        value=data['items'][0]
        self.assertEqual((value['id'],value['amount'],value['currency'],value['accounting_date']),
            (str(self.saved.id),'12.00','GBP','2026-11-06'))
        self.assertEqual((value['period_id'],value['expense_account_id'],value['created_by']),
            (str(self.period),str(self.account),str(self.user)))
        self.assertEqual(value['source']['kind'],'extracted')
        self.assertEqual((value['source']['row'],value['source']['column']),(2,2))
        self.assertEqual(value['source']['job_id'],str(self.job))
        self.assertEqual(self.listing().json()['data'],data)
        self.assertIn('no-store',response.headers['cache-control'])
        self.assertNotIn(self.original.decode(),response.text)
        self.assertEqual(self.rows('csv_expense_drafts'),1)

    def test_viewer_scopes_agent_revocation_and_fresh_direct_service_authority(self):
        self.prepare(); token=self.token(scope=SCOPES)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.listing(self.saved.id).status_code,200)
        for scopes in ['records:read','evidence:read','filings:approve']:
            self.assertEqual(self.listing(headers=self.headers(scope=scopes)).status_code,403)
        for assignment in ["actor_kind='agent'","actor_kind='human',disabled_at=now()",
                           'disabled_at=NULL,tokens_valid_after='+str(self.iat)]:
            self.owner.execute('UPDATE omnixat.identities SET '+assignment+' WHERE id=%s',(self.user,))
            with self.draft_connections() as connection:
                self.assertEqual(read_expense_drafts(connection,self.verifier,token,self.a,self.org,self.evidence)['items'],[])
        self.owner.execute("UPDATE omnixat.identities SET tokens_valid_after=0 WHERE id=%s",(self.user,))
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.listing().status_code,403)
        with self.draft_connections() as connection,self.assertRaises(KeyError):
            read_expense_drafts(connection,self.verifier,token,self.a,self.org,self.evidence,self.saved.id)

    def test_tenant_organisation_evidence_and_draft_binding(self):
        self.prepare()
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'viewer',NULL)",(self.b,self.user))
        for url in [self.draft_url.replace(self.a,self.b),self.draft_url.replace(str(self.org),str(uuid4())),
                    self.draft_url.replace(self.evidence,str(uuid4()))+'/'+str(self.saved.id),
                    self.draft_url+'/'+str(uuid4())]:
            self.assertEqual(self.listing(url=url).status_code,404,url)
        with self.draft_connections() as connection:
            self.assertEqual(read_expense_drafts(connection,self.verifier,self.token(scope=SCOPES),self.b,self.org,self.evidence)['items'],[])

    def test_source_claim_policy_and_accounting_gates_rechecked(self):
        self.prepare()
        changes=[('UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false','UPDATE omnixat.expense_accounting_periods SET open_for_drafts=true'),
                 ('UPDATE omnixat.expense_account_policy SET eligible_for_drafts=false','UPDATE omnixat.expense_account_policy SET eligible_for_drafts=true')]
        for disable,restore in changes:
            self.owner.execute(disable)
            self.assertEqual(self.listing(self.saved.id).status_code,404)
            self.assertEqual(self.listing().json()['data']['items'],[])
            self.owner.execute(restore)
        self.owner.execute("INSERT INTO omnixat.evidence_scan_claims VALUES (%s,%s,'fictional-v1',%s,now()+interval '1 minute')",(self.a,self.evidence,uuid4()))
        self.assertEqual(self.listing(self.saved.id).status_code,404)
        self.owner.execute('DELETE FROM omnixat.evidence_scan_claims WHERE tenant_id=%s',(self.a,))
        self.policy('fictional-v2'); self.assertEqual(self.listing(self.saved.id).status_code,404)
        self.policy('fictional-v1'); self.verdict('blocked')
        self.assertEqual(self.listing(self.saved.id).status_code,404)
        self.assertEqual(self.rows('csv_expense_drafts'),1)

    def test_read_only_role_context_cleanup_and_existing_interactive_guard(self):
        self.prepare()
        with self.draft_connections() as connection:
            read_expense_drafts(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence)
            for setting in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(setting,)).fetchone()[0],('',None))
            for query in ['SELECT * FROM omnixat.csv_expense_drafts','SELECT * FROM omnixat.evidence_quarantine',
                          'SELECT * FROM omnixat_extraction.read_csv_expense_draft(NULL,NULL)']:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): connection.execute(query)
            bearer=Principal(str(self.user),self.a,'owner',api_scopes=frozenset({'records:read','evidence:read','filings:approve'}))
            with self.assertRaises(PermissionError): read_csv_expense_draft(connection,bearer,self.a,self.org,self.saved.id)
        for dsn in [self.runtime_dsn,self.extract_dsn,self.owner_dsn,self.draft_write_dsn]:
            with psycopg.connect(dsn,autocommit=True) as connection,self.assertRaises(PermissionError):
                read_expense_drafts(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence)

    def test_route_opt_in_and_strict_read_only_parameters(self):
        self.prepare()
        for suffix in ['?limit=100','?approve=true']:
            self.assertEqual(self.listing(url=self.draft_url+suffix).status_code,400)
        self.assertEqual(self.listing(draft='bad').status_code,400)
        self.assertEqual(self.listing(headers={'Idempotency-Key':'fictional'}).status_code,400)
        self.assertEqual(self.client.post(self.draft_url,json={},headers=self.headers()).status_code,405)
        self.assertTrue(self.client.get(self.base+'/context',headers=self.headers()).json()['data']['expense_draft_access'])
        with TestClient(self.draft_app(enabled=False),base_url=self.origin) as client:
            self.assertEqual(client.get(self.draft_url,headers=self.headers()).status_code,404)
            self.assertFalse(client.get(self.base+'/context',headers=self.headers()).json()['data']['expense_draft_access'])

    def test_bounded_latest_listing_and_older_exact_lookup(self):
        self.prepare()
        for _ in range(21): self.add_draft(uuid4())
        data=self.listing().json()['data']
        self.assertEqual(len(data['items']),20); self.assertTrue(data['has_more'])
        self.assertNotIn(str(self.saved.id),[v['id'] for v in data['items']])
        self.assertEqual(self.listing(self.saved.id).json()['data']['items'][0]['id'],str(self.saved.id))

    def test_complete_read_chain_without_bypassrls_function_owner(self):
        self.prepare()
        # Transfer the complete extraction/read chain to a read-only non-owner role.
        functions=self.owner.execute("""SELECT p.oid::regprocedure::text,pg_get_userbyid(p.proowner)
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname IN ('omnixat_extraction','omnixat_customer_drafts')""").fetchall()
        def restore():
            for function,owner in functions:
                self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(owner)))
        self.addCleanup(restore)
        self.owner.execute(sql.SQL('GRANT USAGE,CREATE ON SCHEMA omnixat_extraction,omnixat_customer_drafts TO {}').format(sql.Identifier(self.draft_definer_role)))
        self.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat TO {}').format(sql.Identifier(self.draft_definer_role)))
        self.owner.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA omnixat,omnixat_extraction TO {}').format(sql.Identifier(self.draft_definer_role)))
        for function,_ in functions:
            self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(self.draft_definer_role)))
        self.assertEqual(self.listing(self.saved.id).status_code,200)
        self.owner.execute('UPDATE omnixat.identities SET disabled_at=now() WHERE id=%s',(self.user,))
        with self.draft_connections() as connection:
            self.assertEqual(read_expense_drafts(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence)['items'],[])
