"""Fictional customer journal preview/save capabilities against real PostgreSQL."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient
from test_customer_expense_funding import ExpenseFundingFixture
from test_customer_evidence import SCOPES
from omnixat_core.customer_web import create_app
from omnixat_core.customer_expense_journals import FUNCTIONS, inspect_journal, preview_journal, create_journal


class ExpenseJournalFixture(ExpenseFundingFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for label,function in FUNCTIONS.items():
            role=cls.role+'_journal_'+label;password=uuid4().hex
            setattr(cls,'journal_'+label+'_role',role)
            setattr(cls,'journal_'+label+'_dsn',make_conninfo(cls.admin_dsn,dbname=cls.database,user=role,password=password))
            cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(role),sql.Literal(password)))
            def cleanup(role=role):
                cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            cls.addClassCleanup(cleanup)
            cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_customer_journals TO {}').format(sql.Identifier(role)))
            cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_customer_journals.'+function+' TO {}').format(sql.Identifier(role)))

    def setUp(self):
        super().setUp()
        self.journal_factories={}
        for label in FUNCTIONS:
            @contextmanager
            def factory(label=label):
                with psycopg.connect(getattr(self,'journal_'+label+'_dsn'),autocommit=True) as connection:yield connection
            self.journal_factories[label]=factory
        self.app=self.journal_app()
        self.client=TestClient(self.app,base_url=self.origin);self.addCleanup(self.client.close)

    def journal_app(self,enabled=True):
        return create_app(verifier=self.verifier,connection_factory=self.records_factory,
            directory_connection_factory=self.directory_factory,public_origin=self.origin,evidence_quarantine_dir=self.spool.name,
            expense_draft_connection_factory=self.draft_connections,
            expense_journal_read_connection_factory=self.journal_factories['inspect'] if enabled else None,
            expense_journal_preview_connection_factory=self.journal_factories['preview'] if enabled else None,
            expense_journal_write_connection_factory=self.journal_factories['create'] if enabled else None,
            expense_funding_write_connection_factory=self.fund_writes)

    def prepare_journal(self):
        self.prepare_funding();self.assertEqual(self.record().status_code,200)
        self.counterpart,self.other_counterpart=uuid4(),uuid4()
        for account in (self.counterpart,self.other_counterpart,self.account):
            self.owner.execute('INSERT INTO omnixat.expense_counterpart_policy VALUES (%s,%s,%s,%s,true)',(self.a,self.org,self.personal_source,account))
        self.journal_url=self.draft_url+'/'+str(self.saved.id)+'/journal'
        self.journal_document={'counterpart_account_id':str(self.counterpart)}

    def inspect_journal(self,headers=None,url=None):
        return self.client.get(url or self.journal_url,headers=self.headers()|(headers or {}))

    def preview_journal(self,document=None,headers=None,url=None):
        return self.client.post(url or self.journal_url+'-preview',json=self.journal_document if document is None else document,
            headers=self.headers()|{'X-OmniXat-Expected-Actor':str(self.user)}|(headers or {}))

    def save_journal(self,document=None,headers=None,url=None):
        if document is None:
            document=self.journal_document|{'preview_sha256':self.preview_journal().json()['data']['preview_sha256']}
        return self.client.post(url or self.journal_url,json=document,
            headers=self.headers()|{'X-OmniXat-Expected-Actor':str(self.user)}|(headers or {}))


class CustomerExpenseJournalTests(ExpenseJournalFixture):
    def test_explicit_preview_balances_source_save_receipt_and_inspection(self):
        self.prepare_journal();data=self.inspect_journal().json()['data']
        self.assertIsNone(data['journal']);self.assertFalse(data['saved_unavailable'])
        self.assertEqual({x['account_id'] for x in data['choices']},{str(self.counterpart),str(self.other_counterpart)})
        result=self.preview_journal();self.assertEqual(result.status_code,200,result.text);preview=result.json()['data']
        self.assertEqual([x['amount_pence'] for x in preview['lines']],['1200','1200'])
        self.assertEqual([x['side'] for x in preview['lines']],['debit','credit'])
        self.assertEqual([x['amount'] for x in preview['lines']],['12.00','12.00'])
        self.assertEqual(preview['source']['job_id'],str(self.job));self.assertEqual(self.rows('expense_journal_drafts'),0)
        document=self.journal_document|{'preview_sha256':preview['preview_sha256']}
        first=self.save_journal(document);self.assertEqual(first.status_code,201,first.text)
        self.assertEqual(self.save_journal(document).json()['data'],first.json()['data'])
        data=self.inspect_journal().json()['data'];saved=data['journal']
        self.assertEqual(saved['created_by'],str(self.user));self.assertEqual(saved['id'],first.json()['data']['id'])
        self.assertEqual(saved['lines'],preview['lines']);self.assertEqual(len(saved['snapshot_sha256']),64)
        self.assertNotEqual(saved['snapshot_sha256'],preview['preview_sha256']);self.assertEqual(data['choices'],[])
        self.assertEqual(self.rows('expense_journal_drafts'),1);self.assertEqual(self.rows('expense_journal_review_decisions'),0)
        self.assertIn('no-store',result.headers['cache-control']);self.assertNotIn(self.original.decode(),result.text)

    def test_changed_preview_rolls_back_and_concurrent_retry_preserves_receipt(self):
        self.prepare_journal();preview=self.preview_journal().json()['data']
        document=self.journal_document|{'preview_sha256':'0'*64}
        result=self.save_journal(document);self.assertEqual(result.status_code,409,result.text)
        self.assertEqual(result.json()['error']['code'],'journal_preview_changed');self.assertEqual(self.rows('expense_journal_drafts'),0)
        document['preview_sha256']=preview['preview_sha256']
        with ThreadPoolExecutor(max_workers=2) as workers:responses=list(workers.map(lambda _:self.save_journal(document),range(2)))
        self.assertEqual([r.status_code for r in responses],[201,201]);self.assertEqual(responses[0].json()['data'],responses[1].json()['data'])
        other=self.journal_document|{'counterpart_account_id':str(self.other_counterpart)}
        digest=self.preview_journal(other).json()['data']['preview_sha256']
        self.assertEqual(self.save_journal(other|{'preview_sha256':digest}).status_code,409)
        self.assertEqual(self.rows('expense_journal_drafts'),1)

    def test_current_funding_account_source_policy_and_retained_unavailable(self):
        self.prepare_journal();digest=self.preview_journal().json()['data']['preview_sha256']
        doc=self.journal_document|{'preview_sha256':digest}
        self.assertEqual(self.preview_journal({'counterpart_account_id':str(self.account)}).status_code,404)
        self.owner.execute('UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=false WHERE account_id=%s',(self.counterpart,))
        self.assertEqual(self.save_journal(doc).status_code,404)
        self.owner.execute('UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=true WHERE account_id=%s',(self.counterpart,))
        self.assertEqual(self.save_journal(doc).status_code,201)
        self.owner.execute('UPDATE omnixat.expense_funding_sources SET eligible_for_drafts=false WHERE id=%s',(self.personal_source,))
        data=self.inspect_journal().json()['data'];self.assertIsNone(data['journal']);self.assertTrue(data['saved_unavailable']);self.assertEqual(data['choices'],[])
        self.assertEqual(self.preview_journal().status_code,404);self.assertEqual(self.save_journal(doc).status_code,404)
        self.assertEqual(self.rows('expense_journal_drafts'),1)

    def test_tenant_evidence_draft_and_preview_account_binding(self):
        self.prepare_journal();preview=self.preview_journal().json()['data']
        doc=self.journal_document|{'preview_sha256':preview['preview_sha256']}
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        for url in [self.journal_url.replace(self.a,self.b),self.journal_url.replace(self.evidence,str(uuid4())),
                    self.journal_url.replace(str(self.org),str(uuid4())),self.journal_url.replace(str(self.saved.id),str(uuid4()))]:
            self.assertEqual(self.inspect_journal(url=url).status_code,404)
            self.assertEqual(self.preview_journal(url=url+'-preview').status_code,404)
            self.assertEqual(self.save_journal(doc,url=url).status_code,404)
        self.assertEqual(self.save_journal(doc|{'counterpart_account_id':str(self.other_counterpart)}).status_code,409)
        self.assertEqual(self.rows('expense_journal_drafts'),0)

    def test_scopes_viewer_actor_revocation_and_no_agent_authority(self):
        self.prepare_journal();doc=self.journal_document|{'preview_sha256':self.preview_journal().json()['data']['preview_sha256']}
        self.assertEqual(self.preview_journal(headers={'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        self.assertEqual(self.save_journal(doc,headers={'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        self.assertEqual(self.preview_journal(headers=self.headers(scope='records:read evidence:read')).status_code,403)
        self.assertEqual(self.inspect_journal(headers=self.headers(scope='records:read evidence:read')).json()['data']['choices'],[])
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.inspect_journal().json()['data']['choices'],[])
        self.assertEqual(self.preview_journal().status_code,403);self.assertEqual(self.save_journal(doc).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor' WHERE user_id=%s",(self.user,))
        for assignment in ["actor_kind='agent'","actor_kind='human',disabled_at=now()",'disabled_at=NULL,tokens_valid_after='+str(self.iat)]:
            self.owner.execute('UPDATE omnixat.identities SET '+assignment+' WHERE id=%s',(self.user,))
            for operation,service,args in [('inspect',inspect_journal,()),('preview',preview_journal,(self.journal_document,)),('create',create_journal,(doc,))]:
                with self.journal_factories[operation]() as connection,self.assertRaises(PermissionError):
                    service(connection,self.verifier,self.token(scope=SCOPES),self.a,self.org,self.evidence,self.saved.id,*args,
                        **({'expected_actor':self.user} if args else {}))
        self.assertEqual(self.rows('expense_journal_drafts'),0)

    def test_strict_documents_bounds_disabled_routes_and_mixed_grants(self):
        self.prepare_journal()
        for document in [{},self.journal_document|{'amount':'12'},self.journal_document|{'counterpart_account_id':None},
                         {'counterpart_account_id':'00000000-0000-0000-0000-000000000000'}]:
            self.assertEqual(self.preview_journal(document).status_code,422)
        for digest in [None,'','A'*64,'g'*64,0]:
            self.assertEqual(self.save_journal(self.journal_document|{'preview_sha256':digest}).status_code,422)
        self.assertEqual(self.preview_journal(url=self.journal_url+'-preview?approve=true').status_code,400)
        self.assertEqual(self.inspect_journal(url=self.journal_url+'?limit=100').status_code,400)
        for _ in range(21):self.owner.execute('INSERT INTO omnixat.expense_counterpart_policy VALUES (%s,%s,%s,%s,true)',(self.a,self.org,self.personal_source,uuid4()))
        data=self.inspect_journal().json()['data'];self.assertEqual(len(data['choices']),20);self.assertTrue(data['has_more'])
        with TestClient(self.journal_app(False),base_url=self.origin) as client:
            self.assertEqual(client.get(self.journal_url,headers=self.headers()).status_code,404)
        token=self.token(scope=SCOPES)
        with self.journal_factories['inspect']() as connection:
            inspect_journal(connection,self.verifier,token,self.a,self.org,self.evidence,self.saved.id)
            for setting in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(setting,)).fetchone()[0],('',None))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):connection.execute('SELECT * FROM omnixat.expense_journal_drafts')
        self.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_customer_journals.'+FUNCTIONS['preview']+' TO {}').format(sql.Identifier(self.journal_inspect_role)))
        try:
            with self.journal_factories['inspect']() as connection,self.assertRaises(PermissionError):
                inspect_journal(connection,self.verifier,token,self.a,self.org,self.evidence,self.saved.id)
        finally:self.owner.execute(sql.SQL('REVOKE EXECUTE ON FUNCTION omnixat_customer_journals.'+FUNCTIONS['preview']+' FROM {}').format(sql.Identifier(self.journal_inspect_role)))

    def test_changed_accounting_context_requires_fresh_preview(self):
        self.prepare_journal();doc=self.journal_document|{'preview_sha256':self.preview_journal().json()['data']['preview_sha256']}
        self.owner.execute("UPDATE omnixat.csv_expense_drafts SET accounting_date='2026-11-07' WHERE id=%s",(self.saved.id,))
        result=self.save_journal(doc);self.assertEqual(result.status_code,409,result.text)
        self.assertEqual(result.json()['error']['code'],'journal_preview_changed');self.assertEqual(self.rows('expense_journal_drafts'),0)
        fresh=self.preview_journal().json()['data'];self.assertEqual(fresh['accounting_date'],'2026-11-07')
        self.assertNotEqual(fresh['preview_sha256'],doc['preview_sha256'])
        self.assertEqual(self.save_journal(self.journal_document|{'preview_sha256':fresh['preview_sha256']}).status_code,201)

    def test_no_funding_or_wrong_source_mapping_cannot_preview(self):
        self.prepare_journal()
        self.owner.execute('DELETE FROM omnixat.expense_funding_context WHERE draft_id=%s',(self.saved.id,))
        self.assertEqual(self.inspect_journal().json()['data']['choices'],[]);self.assertEqual(self.preview_journal().status_code,404)
        business={'funding_source_id':str(self.business_source),'payer_id':str(self.business_payer)}
        self.assertEqual(self.record(business).status_code,200)
        self.assertEqual(self.inspect_journal().json()['data']['choices'],[]);self.assertEqual(self.preview_journal().status_code,404)
        self.assertEqual(self.rows('expense_journal_drafts'),0)

    def test_complete_read_preview_save_chain_with_non_bypassrls_definer(self):
        self.prepare_journal()
        functions=self.owner.execute("""SELECT p.oid::regprocedure::text,pg_get_userbyid(p.proowner)
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname IN ('omnixat_extraction','omnixat_customer_journals')""").fetchall()
        def restore():
            for function,owner in functions:self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(owner)))
        self.addCleanup(restore)
        for grant in ['USAGE,CREATE ON SCHEMA omnixat_extraction,omnixat_customer_journals','USAGE ON SCHEMA omnixat',
                      'SELECT ON ALL TABLES IN SCHEMA omnixat,omnixat_extraction','INSERT ON omnixat.expense_journal_drafts',
                      'UPDATE ON omnixat.identities,omnixat.memberships,omnixat.csv_expense_drafts,omnixat_extraction.active_scan_policy,omnixat.expense_accounting_periods,omnixat.expense_account_policy,omnixat.evidence_quarantine,omnixat.evidence_registrations,omnixat.evidence_scan_claims,omnixat.expense_funding_sources,omnixat.expense_funding_context,omnixat.expense_counterpart_policy,omnixat.evidence_draft_amounts,omnixat.csv_extraction_results']:
            self.owner.execute(sql.SQL('GRANT '+grant+' TO {}').format(sql.Identifier(self.draft_definer_role)))
        for function,_ in functions:self.owner.execute(sql.SQL('ALTER FUNCTION '+function+' OWNER TO {}').format(sql.Identifier(self.draft_definer_role)))
        self.assertIsNone(self.inspect_journal().json()['data']['journal'])
        preview=self.preview_journal();self.assertEqual(preview.status_code,200,preview.text)
        result=self.save_journal(self.journal_document|{'preview_sha256':preview.json()['data']['preview_sha256']})
        self.assertEqual(result.status_code,201,result.text)
        self.assertEqual(self.inspect_journal().json()['data']['journal']['created_by'],str(self.user))

    def test_save_holds_identity_and_shared_accounting_source_gates_until_commit(self):
        from uuid import UUID
        from omnixat_core.postgres import _tenant_transaction
        self.prepare_journal();digest=bytes.fromhex(self.preview_journal().json()['data']['preview_sha256'])
        with self.journal_factories['create']() as connection:
            with _tenant_transaction(connection,UUID(self.a),write=True,tables_required=('expense_journal_drafts',)):
                connection.execute('SELECT * FROM omnixat_customer_journals.create_draft(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (self.issuer,self.subject,self.iat,self.org,self.evidence,self.saved.id,self.user,self.counterpart,digest)).fetchone()
                for query,params in [
                    ('UPDATE omnixat.identities SET disabled_at=now() WHERE id=%s',(self.user,)),
                    ('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user)),
                    ("UPDATE omnixat_extraction.active_scan_policy SET policy_version='fictional-v2'",()),
                    ('UPDATE omnixat.expense_accounting_periods SET open_for_drafts=false WHERE tenant_id=%s',(self.a,)),
                    ('UPDATE omnixat.expense_funding_sources SET eligible_for_drafts=false WHERE id=%s',(self.personal_source,)),
                    ('UPDATE omnixat.expense_counterpart_policy SET eligible_for_drafts=false WHERE account_id=%s',(self.counterpart,)),
                    ("UPDATE omnixat.csv_expense_drafts SET accounting_date='2026-11-07' WHERE id=%s",(self.saved.id,)),
                    ("INSERT INTO omnixat.evidence_scan_verdicts SELECT tenant_id,evidence_id,content_sha256,byte_size,'fictional-v1','blocked',now() FROM omnixat.evidence_quarantine WHERE tenant_id=%s AND evidence_id=%s",(self.a,self.evidence))]:
                    with self.subTest(query=query),self.assertRaises(psycopg.errors.LockNotAvailable):
                        with self.owner.transaction():
                            self.owner.execute("SET LOCAL lock_timeout='40ms'");self.owner.execute(query,params)
        self.assertEqual(self.inspect_journal().json()['data']['journal']['created_by'],str(self.user))
