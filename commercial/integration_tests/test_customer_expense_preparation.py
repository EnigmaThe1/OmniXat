"""Atomic customer expense preparation from fictional persisted CSV evidence."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_customer_expense_drafts import CustomerExpenseDraftFixture
from omnixat_core.customer_web import create_app
from omnixat_core.customer_expense_preparation import create_expense, expense_choices

CHOICES='omnixat_customer_preparation.expense_choices(text,text,bigint,uuid,uuid)'
CREATE='omnixat_customer_preparation.create_expense(text,text,bigint,uuid,uuid,uuid,uuid,text,integer,integer,uuid,uuid,date)'


class ExpensePreparationFixture(CustomerExpenseDraftFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.preparation_role=cls.role+'_prepare'; password=uuid4().hex
        cls.preparation_dsn=make_conninfo(cls.admin_dsn,dbname=cls.database,user=cls.preparation_role,password=password)
        cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(cls.preparation_role),sql.Literal(password)))
        def cleanup():
            cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(cls.preparation_role)))
            cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(cls.preparation_role)))
        cls.addClassCleanup(cleanup)
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_preparation TO {}').format(sql.Identifier(cls.preparation_role)))
        for function in [CHOICES,CREATE]:
            cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+function+' TO {}').format(sql.Identifier(cls.preparation_role)))

    def setUp(self):
        super().setUp()
        @contextmanager
        def preparation_connections():
            with psycopg.connect(self.preparation_dsn,autocommit=True) as connection: yield connection
        self.preparation_connections=preparation_connections
        self.app=create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,
            evidence_quarantine_dir=self.spool.name,csv_review_connection_factory=self.review_connections,
            expense_draft_connection_factory=self.draft_connections,
            expense_preparation_connection_factory=preparation_connections)
        self.client=TestClient(self.app,base_url=self.origin); self.addCleanup(self.client.close)

    def prepare_source(self,original=None):
        if original is not None:
            self.evidence=self.upload(content=original).json()['data']['id']; self.job=uuid4()
        self.policy(); self.verdict('clean'); self.extract()
        self.period,self.account=uuid4(),uuid4()
        self.owner.execute("INSERT INTO omnixat.expense_accounting_periods VALUES (%s,%s,%s,'2026-11-01','2026-11-30',true)",(self.a,self.org,self.period))
        self.owner.execute('INSERT INTO omnixat.expense_account_policy VALUES (%s,%s,%s,true)',(self.a,self.org,self.account))
        self.draft_url=self.url+'/'+self.evidence+'/expense-drafts'
        self.choices_url=self.url+'/'+self.evidence+'/expense-choices'
        self.document={'job_id':str(self.job),'field_name':'amount','row':2,'column':2,
            'period_id':str(self.period),'expense_account_id':str(self.account),'accounting_date':'2026-11-06'}

    def save(self,document=None,headers=None,url=None):
        return self.client.post(url or self.draft_url,json=self.document if document is None else document,
            headers=self.headers()|{'X-OmniXat-Expected-Actor':str(self.user)}|(headers or {}))

    def choices(self): return self.client.get(self.choices_url,headers=self.headers())


class ExpensePreparationTests(ExpensePreparationFixture):
    def test_explicit_choices_atomic_create_retry_and_customer_review(self):
        self.prepare_source(); choices=self.choices()
        self.assertEqual(choices.status_code,200,choices.text)
        data=choices.json()['data']; self.assertEqual(data['periods'],[{'id':str(self.period),'starts_on':'2026-11-01','ends_on':'2026-11-30'}])
        self.assertEqual(data['accounts'],[{'id':str(self.account)}])
        first=self.save(); self.assertEqual(first.status_code,201,first.text)
        receipt=first.json()['data']; self.assertEqual(set(receipt),{'id','created_at'})
        self.assertEqual(self.save().json()['data'],receipt)
        self.assertEqual((self.rows('evidence_draft_amounts'),self.rows('csv_expense_drafts')),(1,1))
        saved=self.listing(receipt['id']).json()['data']['items'][0]
        self.assertEqual(saved['amount'],'12.00'); self.assertEqual(saved['created_by'],str(self.user))
        self.assertEqual(saved['source']['kind'],'extracted')
        # A fictional prior human answer is a separate attributed source, never
        # an amount accepted in the preparation document.
        self.owner.execute("INSERT INTO omnixat.csv_clarification_answers VALUES (%s,%s,'missing_amount',3,2,'23.450',%s,now())",(self.a,self.job,str(self.user)))
        clarified=self.save(self.document|{'field_name':'missing_amount','row':3})
        self.assertEqual(clarified.status_code,201,clarified.text)
        value=self.listing(clarified.json()['data']['id']).json()['data']['items'][0]
        self.assertEqual((value['amount'],value['source']['kind']),('23.450','clarified'))

    def test_rejected_context_and_unresolved_source_leave_no_partial_amount(self):
        self.prepare_source()
        for change in [{'period_id':str(uuid4())},{'expense_account_id':str(uuid4())},
                       {'accounting_date':'2026-12-01'},{'field_name':'missing_amount','row':3}]:
            response=self.save(self.document|change)
            self.assertIn(response.status_code,[404,422],response.text)
            self.assertEqual((self.rows('evidence_draft_amounts'),self.rows('csv_expense_drafts')),(0,0))
        self.owner.execute('UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false WHERE tenant_id=%s',(self.a,))
        self.assertEqual(self.save().status_code,422)
        self.assertEqual(self.rows('evidence_draft_amounts'),0)

    def test_negative_and_non_penny_amounts_rejected_without_side_effect(self):
        for value in [b'-1.00',b'12.345',b'0.00']:
            self.prepare_source(original=b'Fictional,Amount\r\nFictional purchase,'+value+b'\r\n')
            self.assertEqual(self.save().status_code,422)
            self.assertEqual((self.rows('evidence_draft_amounts'),self.rows('csv_expense_drafts')),(0,0))

    def test_scopes_persisted_identity_actor_continuity_and_revocation(self):
        self.prepare_source()
        self.assertEqual(self.save(headers={'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        for scopes in ['records:read evidence:read','records:read records:write']:
            self.assertEqual(self.save(headers=self.headers(scope=scopes)).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.choices().status_code,403); self.assertEqual(self.save().status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor' WHERE user_id=%s",(self.user,))
        for assignment in ["actor_kind='agent'","actor_kind='human',disabled_at=now()",
                           'disabled_at=NULL,tokens_valid_after='+str(self.iat)]:
            self.owner.execute('UPDATE omnixat.identities SET '+assignment+' WHERE id=%s',(self.user,))
            with self.preparation_connections() as connection,self.assertRaises(PermissionError):
                create_expense(connection,self.verifier,self.token(scope='records:read records:write evidence:read'),self.a,self.org,self.evidence,self.document,expected_actor=self.user)
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=0 WHERE id=%s',(self.user,))
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.save().status_code,403)
        self.assertEqual(self.rows('evidence_draft_amounts'),0)

    def test_concurrent_retry_and_conflict_preserve_original_preparation(self):
        self.prepare_source()
        with ThreadPoolExecutor(max_workers=2) as workers:
            responses=list(workers.map(lambda _:self.save(),range(2)))
        self.assertEqual([r.status_code for r in responses],[201,201])
        self.assertEqual(responses[0].json()['data'],responses[1].json()['data'])
        self.assertEqual(self.save(self.document|{'accounting_date':'2026-11-07'}).status_code,409)
        self.assertEqual((self.rows('evidence_draft_amounts'),self.rows('csv_expense_drafts')),(1,1))

    def test_source_policy_claims_scope_and_strict_body(self):
        self.prepare_source()
        for change in [{'amount':'999'},{'approved':True},{'currency':'USD'},{'row':True},
                       {'job_id':'bad'},{'accounting_date':'20261106'},{'accounting_date':None}]:
            self.assertEqual(self.save(self.document|change).status_code,422,change)
        self.assertEqual(self.save(url=self.draft_url+'?approve=true').status_code,400)
        self.assertEqual(self.save(headers={'Origin':'https://other.example'}).status_code,403)
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        self.assertEqual(self.save(url=self.draft_url.replace(self.a,self.b)).status_code,404)
        self.owner.execute("INSERT INTO omnixat.evidence_scan_claims VALUES (%s,%s,'fictional-v1',%s,now()+interval '1 minute')",(self.a,self.evidence,uuid4()))
        self.assertEqual(self.save().status_code,404)
        self.owner.execute('DELETE FROM omnixat.evidence_scan_claims WHERE tenant_id=%s',(self.a,))
        self.policy('fictional-v2'); self.assertEqual(self.save().status_code,404)
        self.policy('fictional-v1'); self.verdict('blocked'); self.assertEqual(self.save().status_code,404)
        self.assertEqual(self.rows('evidence_draft_amounts'),0)

    def test_bounded_choices_context_cleanup_and_narrow_runtime_grants(self):
        self.prepare_source()
        for _ in range(21):
            self.owner.execute("INSERT INTO omnixat.expense_accounting_periods VALUES (%s,%s,%s,'2026-11-01','2026-11-30',true)",(self.a,self.org,uuid4()))
            self.owner.execute('INSERT INTO omnixat.expense_account_policy VALUES (%s,%s,%s,true)',(self.a,self.org,uuid4()))
        choices=self.choices().json()['data']
        self.assertEqual((len(choices['periods']),len(choices['accounts'])),(20,20))
        self.assertTrue(choices['has_more_periods']); self.assertTrue(choices['has_more_accounts'])
        with self.preparation_connections() as connection:
            expense_choices(connection,self.verifier,self.token(scope='records:read records:write evidence:read'),self.a,self.org,self.evidence)
            for setting in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(setting,)).fetchone()[0],('',None))
            for query in ['SELECT * FROM omnixat.evidence_quarantine','SELECT * FROM omnixat.csv_expense_drafts']:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege): connection.execute(query)
        for dsn in [self.runtime_dsn,self.extract_dsn,self.owner_dsn,self.draft_review_dsn]:
            with psycopg.connect(dsn,autocommit=True) as connection,self.assertRaises(PermissionError):
                create_expense(connection,self.verifier,self.token(scope='records:read records:write evidence:read'),self.a,self.org,self.evidence,self.document,expected_actor=self.user)

    def test_full_write_chain_under_non_bypassrls_owner(self):
        self.prepare_source()
        functions=self.owner.execute("""SELECT p.oid::regprocedure::text,pg_get_userbyid(p.proowner)
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname IN ('omnixat_extraction','omnixat_customer_preparation')""").fetchall()
        def restore():
            for function,owner in functions:
                self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(owner)))
        self.addCleanup(restore)
        for grant in ['USAGE,CREATE ON SCHEMA omnixat_extraction,omnixat_customer_preparation','USAGE ON SCHEMA omnixat',
                      'SELECT ON ALL TABLES IN SCHEMA omnixat,omnixat_extraction',
                      'INSERT ON omnixat.evidence_draft_amounts,omnixat.csv_expense_drafts',
                      'UPDATE ON omnixat.identities,omnixat.memberships,omnixat_extraction.active_scan_policy,omnixat.expense_accounting_periods,omnixat.expense_account_policy,omnixat.evidence_quarantine,omnixat.evidence_scan_claims']:
            self.owner.execute(sql.SQL('GRANT '+grant+' TO {}').format(sql.Identifier(self.draft_definer_role)))
        for function,_ in functions:
            self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(self.draft_definer_role)))
        response=self.save(); self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(self.save().json()['data'],response.json()['data'])
        self.assertEqual(self.listing(response.json()['data']['id']).status_code,200)
        # Lock visibility must not grant identity/membership mutation, even to
        # the non-bypass function owner with explicit UPDATE table privileges.
        from omnixat_core.postgres import _tenant_transaction
        from uuid import UUID
        for query in ['UPDATE omnixat.identities SET disabled_at=now() WHERE id=%s',
                      "UPDATE omnixat.memberships SET role='owner' WHERE user_id=%s"]:
            with psycopg.connect(self.draft_definer_dsn,autocommit=True) as connection:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with _tenant_transaction(connection,UUID(self.a),write=True,tables_required=('identities','memberships')):
                        connection.execute("SELECT set_config('omnixat.issuer',%s,true),set_config('omnixat.subject',%s,true)",(self.issuer,self.subject))
                        connection.execute(query,(self.user,))
