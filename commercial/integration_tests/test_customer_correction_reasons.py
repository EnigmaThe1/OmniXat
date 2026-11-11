"""Fictional structured correction requests; no amount correction or approval."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID, uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_customer_bookkeeping_observations import BookkeepingObservationFixture
from test_customer_evidence import SCOPES
from omnixat_core.customer_web import create_app
from omnixat_core.customer_correction_reasons import FUNCTIONS, read_corrections, record_reason
from omnixat_core.journal_correction_questions import journal_correction_questions


class CorrectionReasonFixture(BookkeepingObservationFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for operation,function in FUNCTIONS.items():
            role=cls.role+'_correction_'+operation;password=uuid4().hex
            setattr(cls,'correction_'+operation+'_role',role)
            setattr(cls,'correction_'+operation+'_dsn',make_conninfo(cls.admin_dsn,dbname=cls.database,user=role,password=password))
            cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(role),sql.Literal(password)))
            def cleanup(role=role):
                cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            cls.addClassCleanup(cleanup)
            cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_corrections TO {}').format(sql.Identifier(role)))
            cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_customer_corrections.'+function+' TO {}').format(sql.Identifier(role)))

    def setUp(self):
        super().setUp();self.correction_factories={}
        for operation in FUNCTIONS:
            @contextmanager
            def factory(operation=operation):
                with psycopg.connect(getattr(self,'correction_'+operation+'_dsn'),autocommit=True) as connection:yield connection
            self.correction_factories[operation]=factory
        self.app=self.correction_app();self.client=TestClient(self.app,base_url=self.origin);self.addCleanup(self.client.close)

    def correction_app(self,read=True,write=True):
        return create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,evidence_quarantine_dir=self.spool.name,
            expense_draft_connection_factory=self.draft_connections,
            expense_journal_read_connection_factory=self.journal_factories['inspect'],expense_journal_preview_connection_factory=self.journal_factories['preview'],
            expense_journal_write_connection_factory=self.journal_factories['create'],expense_funding_write_connection_factory=self.fund_writes,
            journal_observation_connection_factory=self.observation_reads,bookkeeping_observation_connection_factory=self.bookkeeping_writes,
            correction_read_connection_factory=self.correction_factories['read'] if read else None,
            correction_write_connection_factory=self.correction_factories['write'] if write else None)

    def prepare_reason(self,observation=True):
        self.prepare_bookkeeping();self.correction_url=self.journal_url+'-corrections'
        if observation:self.assertEqual(self.record_observation().status_code,200)
        self.reason_document={'snapshot_sha256':self.snapshot,'reason':'amount'}

    def inspect_reasons(self,params=None,headers=None,url=None):
        return self.client.get(url or self.correction_url,params={'snapshot_sha256':self.snapshot} if params is None else params,headers=self.headers()|(headers or {}))

    def request_reason(self,document=None,headers=None,url=None):
        return self.client.post(url or self.correction_url,json=self.reason_document if document is None else document,
            headers=self.headers()|{'X-OmniXat-Expected-Actor':str(self.user)}|(headers or {}))

    def add_reason(self,reviewer,reason):
        self.add_observation(reviewer,'changes_requested')
        self.owner.execute('INSERT INTO omnixat.expense_journal_correction_requests VALUES (%s,%s,%s,%s,%s,DEFAULT,%s,DEFAULT)',
            (self.a,self.org,self.journal['id'],bytes.fromhex(self.snapshot),reviewer,reason))


class CustomerCorrectionReasonTests(CorrectionReasonFixture):
    def test_explicit_reason_stable_receipt_own_context_and_immutable_conflict(self):
        self.prepare_reason();initial=self.inspect_reasons().json()['data']
        self.assertEqual(initial['own']['decision'],'changes_requested');self.assertIn('amount',initial['choices']);self.assertEqual(initial['actor_id'],str(self.user))
        first=self.request_reason();self.assertEqual(first.status_code,200,first.text)
        receipt=first.json()['data'];self.assertEqual(self.request_reason().json()['data'],receipt)
        self.assertEqual(receipt['reviewer_id'],str(self.user));self.assertEqual(receipt['reason'],'amount')
        data=self.inspect_reasons().json()['data'];self.assertEqual(data['own']['reason'],'amount');self.assertEqual(data['choices'],[])
        self.assertEqual(data['items'][0]['correction_reason'],'amount')
        self.assertEqual(data['questions'],[{'reason':'amount','question':journal_correction_questions(['amount'])[0].question}])
        conflict=self.request_reason(self.reason_document|{'reason':'funding'});self.assertEqual(conflict.status_code,409,conflict.text)
        self.assertEqual(conflict.json()['error']['code'],'correction_reason_conflict')
        self.assertEqual(self.rows('expense_journal_correction_requests'),1);self.assertEqual(self.rows('expense_journal_review_decisions'),1)
        self.assertEqual(self.rows('expense_journal_drafts'),1);self.assertIn('no-store',first.headers['cache-control'])

    def test_requires_own_prior_changes_requested_never_creates_observation(self):
        self.prepare_reason(False);self.assertEqual(self.request_reason().status_code,404)
        self.assertEqual(self.rows('expense_journal_review_decisions'),0);self.assertEqual(self.inspect_reasons().json()['data']['choices'],[])
        self.add_reason('fictional-other-reviewer','amount');self.assertEqual(self.request_reason().status_code,404)
        self.assertEqual(self.record_observation(self.document|{'decision':'reviewed'}).status_code,200)
        self.assertEqual(self.request_reason().status_code,404);self.assertEqual(self.rows('expense_journal_correction_requests'),1)

    def test_bounded_pages_deduplicated_questions_and_answer_suppression(self):
        self.prepare_reason()
        for i in range(23):self.add_reason(f'fictional-reviewer-{i:03d}','amount' if i%2 else 'funding')
        first=self.inspect_reasons().json()['data'];self.assertEqual(len(first['items']),20);self.assertTrue(first['has_more'])
        self.assertEqual({q['reason'] for q in first['questions']},{'amount','funding'})
        second=self.inspect_reasons({'snapshot_sha256':self.snapshot,'after_reviewer':first['next_after_reviewer']}).json()['data']
        self.assertEqual(len(second['items']),4);self.assertFalse(second['has_more'])
        self.assertFalse({r['reviewer_id'] for r in first['items']} & {r['reviewer_id'] for r in second['items']})
        answer='Fictional retained clarification body must not be disclosed by this reader'
        self.owner.execute('INSERT INTO omnixat.expense_journal_clarification_answers VALUES (%s,%s,%s,%s,%s,%s,%s,%s,DEFAULT)',
            (self.a,self.org,self.journal['id'],bytes.fromhex(self.snapshot),'fictional-reviewer-001','amount',answer,str(self.user)))
        response=self.inspect_reasons();data=response.json()['data']
        self.assertEqual([q['reason'] for q in data['questions']],['funding']);self.assertNotIn(answer,response.text)
        self.assertTrue(all(r['clarification_recorded'] for r in data['items'] if r['correction_reason']=='amount'))

    def test_concurrent_retry_and_stale_snapshot_current_source_binding(self):
        self.prepare_reason()
        with ThreadPoolExecutor(max_workers=2) as workers:responses=list(workers.map(lambda _:self.request_reason(),range(2)))
        self.assertEqual([r.status_code for r in responses],[200,200]);self.assertEqual(responses[0].json()['data'],responses[1].json()['data'])
        self.owner.execute("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-changed-author' WHERE id=%s",(self.journal['id'],))
        self.assertEqual(self.request_reason().status_code,409);self.assertEqual(self.inspect_reasons().status_code,409)
        self.owner.execute('UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=false WHERE account_id=%s',(self.counterpart,))
        self.assertEqual(self.request_reason().status_code,404);self.assertEqual(self.inspect_reasons().status_code,404)
        self.assertEqual(self.rows('expense_journal_correction_requests'),1)

    def test_tenant_evidence_binding_scopes_roles_actor_and_identity_revocation(self):
        self.prepare_reason();self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        for url in [self.correction_url.replace(self.a,self.b),self.correction_url.replace(self.evidence,str(uuid4())),self.correction_url.replace(str(self.org),str(uuid4())),self.correction_url.replace(str(self.saved.id),str(uuid4()))]:
            self.assertEqual(self.inspect_reasons(url=url).status_code,404);self.assertEqual(self.request_reason(url=url).status_code,404)
        self.assertEqual(self.request_reason(headers={'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        self.assertEqual(self.request_reason(headers=self.headers(scope='records:read evidence:read')).status_code,403)
        self.assertEqual(self.inspect_reasons(headers=self.headers(scope='records:read evidence:read')).json()['data']['choices'],[])
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.inspect_reasons().json()['data']['choices'],[]);self.assertEqual(self.request_reason().status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor' WHERE user_id=%s",(self.user,))
        for assignment in ["actor_kind='agent'","actor_kind='human',disabled_at=now()",'disabled_at=NULL,tokens_valid_after='+str(self.iat)]:
            self.owner.execute('UPDATE omnixat.identities SET '+assignment+' WHERE id=%s',(self.user,))
            for op,service,args,kwargs in [('read',read_corrections,(),{'snapshot_sha256':self.snapshot}),('write',record_reason,(self.reason_document,),{'expected_actor':self.user})]:
                with self.correction_factories[op]() as connection,self.assertRaises(PermissionError):
                    service(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence,self.saved.id,*args,**kwargs)
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=0 WHERE id=%s',(self.user,))
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.request_reason().status_code,403);self.assertEqual(self.rows('expense_journal_correction_requests'),0)

    def test_strict_contract_capability_separation_and_context_cleanup(self):
        self.prepare_reason()
        for doc in [{},self.reason_document|{'reason':'approve'},self.reason_document|{'reason':None},self.reason_document|{'snapshot_sha256':'A'*64},self.reason_document|{'amount':'12'}]:
            self.assertEqual(self.request_reason(doc).status_code,422,doc)
        for params in [{},{'snapshot_sha256':self.snapshot,'after_reviewer':''},{'snapshot_sha256':self.snapshot,'after_reviewer':'x'*201},[('snapshot_sha256',self.snapshot),('snapshot_sha256',self.snapshot)]]:
            self.assertEqual(self.inspect_reasons(params).status_code,400,params)
        self.assertEqual(self.request_reason(url=self.correction_url+'?approve=true').status_code,400)
        with TestClient(self.correction_app(False,False),base_url=self.origin) as client:self.assertEqual(client.get(self.correction_url,headers=self.headers()).status_code,404)
        with self.correction_factories['read']() as connection:
            read_corrections(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence,self.saved.id,snapshot_sha256=self.snapshot)
            for key in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:self.assertIn(connection.execute('SELECT current_setting(%s,true)',(key,)).fetchone()[0],('',None))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):connection.execute('SELECT * FROM omnixat.expense_journal_correction_requests')
        self.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_customer_corrections.'+FUNCTIONS['write']+' TO {}').format(sql.Identifier(self.correction_read_role)))
        try:
            with self.correction_factories['read']() as connection,self.assertRaises(PermissionError):read_corrections(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence,self.saved.id,snapshot_sha256=self.snapshot)
        finally:self.owner.execute(sql.SQL('REVOKE EXECUTE ON FUNCTION omnixat_customer_corrections.'+FUNCTIONS['write']+' FROM {}').format(sql.Identifier(self.correction_read_role)))

    def test_non_bypassrls_complete_chain_and_gate_lock_retention(self):
        from omnixat_core.postgres import _tenant_transaction
        self.prepare_reason();functions=self.owner.execute("""SELECT p.oid::regprocedure::text,pg_get_userbyid(p.proowner) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname IN ('omnixat_extraction','omnixat_customer_journal_decisions','omnixat_customer_corrections')""").fetchall()
        def restore():
            for function,owner in functions:self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(owner)))
        self.addCleanup(restore)
        for grant in ['USAGE,CREATE ON SCHEMA omnixat_extraction,omnixat_customer_journal_decisions,omnixat_customer_corrections','USAGE ON SCHEMA omnixat',
          'SELECT ON ALL TABLES IN SCHEMA omnixat,omnixat_extraction','INSERT ON omnixat.expense_journal_correction_requests,omnixat.expense_journal_review_decisions',
          'UPDATE ON omnixat.identities,omnixat.memberships,omnixat.csv_expense_drafts,omnixat.expense_journal_drafts,omnixat.expense_journal_review_decisions,omnixat_extraction.active_scan_policy,omnixat.expense_accounting_periods,omnixat.expense_account_policy,omnixat.evidence_quarantine,omnixat.evidence_registrations,omnixat.evidence_scan_claims,omnixat.expense_funding_sources,omnixat.expense_funding_context,omnixat.expense_counterpart_policy,omnixat.evidence_draft_amounts,omnixat.csv_extraction_results']:
            self.owner.execute(sql.SQL('GRANT '+grant+' TO {}').format(sql.Identifier(self.draft_definer_role)))
        for function,_ in functions:self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(self.draft_definer_role)))
        self.assertEqual(self.inspect_reasons().status_code,200)
        with self.correction_factories['write']() as connection:
            with _tenant_transaction(connection,UUID(self.a),write=True,tables_required=('expense_journal_correction_requests',)):
                connection.execute('SELECT * FROM omnixat_customer_corrections.record_reason(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (self.issuer,self.subject,self.iat,self.org,self.evidence,self.saved.id,self.user,bytes.fromhex(self.snapshot),'amount')).fetchone()
                for query,params in [('UPDATE omnixat.identities SET disabled_at=now() WHERE id=%s',(self.user,)),
                    ('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user)),
                    ('DELETE FROM omnixat.expense_journal_review_decisions WHERE reviewer_id=%s',(str(self.user),)),
                    ('UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=false WHERE account_id=%s',(self.counterpart,)),
                    ("UPDATE omnixat.expense_journal_drafts SET created_by='fictional-changed-author' WHERE id=%s",(self.journal['id'],)),
                    ("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'",())]:
                    with self.subTest(query=query),self.assertRaises(psycopg.errors.LockNotAvailable):
                        with self.owner.transaction():self.owner.execute("SET LOCAL lock_timeout='40ms'");self.owner.execute(query,params)
        self.assertEqual(self.request_reason().status_code,200);self.assertEqual(self.inspect_reasons().json()['data']['own']['reason'],'amount')
