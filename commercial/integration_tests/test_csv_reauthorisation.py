from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import psycopg
from psycopg import sql
from test_csv_request_lifecycle import CSVRequestLifecycleFixture
from test_customer_csv_requests import REQUEST_SCOPES
from omnixat_core.csv_requests_postgres import reauthorise_csv

REAUTHORISE_FUNCTION='omnixat_csv_requests.reauthorise_csv(text,text,bigint,uuid,uuid,uuid,uuid,timestamptz,uuid)'


class CSVReauthorisationFixture(CSVRequestLifecycleFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION '+REAUTHORISE_FUNCTION+' TO {}').format(sql.Identifier(cls.csv_request_role)))

    def setUp(self):
        super().setUp()
        self.renewal_job=uuid4()

    def cancel_ready(self):
        self.ready(); self.request()
        self.cancelled=self.cancel().json()['data']['cancelled_at']
        self.renewal_document={'job_id':str(self.renewal_job),'cancelled_at':self.cancelled}

    def renew(self,document=None,headers=None,job=None):
        return self.client.post(self.request_url+'/'+str(job or self.job)+'/reauthorisations',
            json=self.renewal_document if document is None else document,
            headers=self.headers(scope=REQUEST_SCOPES)|{'X-OmniXat-Expected-Actor':str(self.user)}|(headers or {}))


class CSVReauthorisationTests(CSVReauthorisationFixture):
    def test_fresh_linked_request_preserves_plan_and_history_then_dispatches(self):
        self.cancel_ready(); parent=self.listing(self.job).json()['data']['items'][0]
        response=self.renew(); self.assertEqual(response.status_code,202,response.text)
        self.assertEqual(response.json()['data']['job_id'],str(self.renewal_job))
        self.assertEqual(self.renew().json()['data'],response.json()['data'])
        records=self.listing().json()['data']['items']; child,old=records
        self.assertEqual(child['selections'],parent['selections']); self.assertEqual(old['cancelled_at'],parent['cancelled_at'])
        self.assertEqual(old['state'],'reauthorised'); self.assertEqual(child['state'],'awaiting_worker')
        self.assertEqual(self.owner.execute('SELECT previous_job_id FROM omnixat.csv_extraction_requests WHERE tenant_id=%s AND job_id=%s',(self.a,self.renewal_job)).fetchone()[0],self.job)
        self.assertEqual(self.requested_worker()[0],1)
        result=self.requested_worker(self.plan()|{'job':str(self.renewal_job)})
        self.assertEqual(result[0],0,result[2]); self.assertEqual(self.rows('csv_extraction_results'),1)

    def test_stale_retry_never_restarts_a_later_child_cancellation(self):
        self.cancel_ready(); first=self.renew(); self.assertEqual(first.status_code,202)
        child_cancel=self.cancel(self.renewal_job).json()['data']['cancelled_at']
        self.assertEqual(self.renew().json()['data'],first.json()['data'])
        self.assertEqual(self.listing(self.renewal_job).json()['data']['items'][0]['state'],'cancelled')
        self.assertEqual(self.requested_worker(self.plan()|{'job':str(self.renewal_job)})[0],1)
        self.assertEqual(self.renew(self.renewal_document|{'job_id':str(uuid4())}).status_code,409)
        grandchild=uuid4()
        self.assertEqual(self.renew({'job_id':str(grandchild),'cancelled_at':child_cancel},job=self.renewal_job).status_code,202)
        self.assertEqual(self.rows('csv_extraction_requests'),3)

    def test_requires_exact_cancellation_and_current_source_for_new_work(self):
        self.ready(); self.request(); self.renewal_document={'job_id':str(self.renewal_job),'cancelled_at':'2026-01-01T00:00:00+00:00'}
        self.assertEqual(self.renew().status_code,409)
        self.cancelled=self.cancel().json()['data']['cancelled_at']; self.renewal_document['cancelled_at']=self.cancelled
        from datetime import datetime
        wrong=(datetime.fromisoformat(self.cancelled)+timedelta(microseconds=1)).isoformat()
        self.assertEqual(self.renew(self.renewal_document|{'cancelled_at':wrong}).status_code,409)
        self.policy('fictional-v2'); self.assertEqual(self.renew().status_code,409)
        self.verdict('clean','fictional-v2'); response=self.renew(); self.assertEqual(response.status_code,202,response.text)
        self.assertEqual(response.json()['data']['policy_version'],'fictional-v2')
        self.assertEqual(self.listing(self.job).json()['data']['items'][0]['policy_version'],'fictional-v1')

    def test_scope_role_identity_and_actor_cannot_be_supplied_by_clients(self):
        self.cancel_ready()
        self.assertEqual(self.renew(headers={'X-OmniXat-Expected-Actor':str(uuid4())}).status_code,409)
        self.assertEqual(self.renew(headers=self.headers()).status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE user_id=%s",(self.user,))
        self.assertEqual(self.renew().status_code,403)
        self.owner.execute("UPDATE omnixat.memberships SET role='editor' WHERE user_id=%s",(self.user,))
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='agent' WHERE id=%s",(self.user,))
        self.assertEqual(self.renew().status_code,403)
        self.owner.execute("UPDATE omnixat.identities SET actor_kind='human',tokens_valid_after=%s WHERE id=%s",(self.iat,self.user))
        with self.csv_request_connections() as connection,self.assertRaises(PermissionError):
            reauthorise_csv(connection,self.verifier,self.token(scope=REQUEST_SCOPES),self.a,self.org,self.evidence,self.job,self.renewal_document,expected_actor=self.user)
        self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=0,disabled_at=now() WHERE id=%s',(self.user,))
        self.assertEqual(self.renew().status_code,403)
        self.owner.execute('UPDATE omnixat.identities SET disabled_at=NULL WHERE id=%s',(self.user,))
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE user_id=%s',(self.user,))
        self.assertEqual(self.renew().status_code,403)
        self.assertEqual(self.rows('csv_extraction_requests'),1)

    def test_concurrent_exact_retries_have_one_linked_child_and_context_clears(self):
        self.cancel_ready(); token=self.token(scope=REQUEST_SCOPES)
        def save(_):
            with self.csv_request_connections() as connection:
                return reauthorise_csv(connection,self.verifier,token,self.a,self.org,self.evidence,self.job,self.renewal_document,expected_actor=self.user)
        with ThreadPoolExecutor(max_workers=3) as executor: results=list(executor.map(save,range(3)))
        self.assertTrue(all(x==results[0] for x in results)); self.assertEqual(self.rows('csv_extraction_requests'),2)
        with self.csv_request_connections() as connection:
            reauthorise_csv(connection,self.verifier,token,self.a,self.org,self.evidence,self.job,self.renewal_document,expected_actor=self.user)
            for key in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(key,)).fetchone()[0],('',None))

    def test_strict_body_tenant_parent_and_fresh_id_prevent_adopting_work(self):
        self.cancel_ready()
        for change in [{'job_id':str(self.job)},{'job_id':'bad'},{'cancelled_at':self.cancelled[:10]},
                       {'cancelled_at':None},{'selections':[]},{'extra':'x'}]:
            self.assertEqual(self.renew(self.renewal_document|change).status_code,422,change)
        self.assertEqual(self.renew(headers={'Origin':'https://other.example'}).status_code,403)
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        url=self.request_url.replace(self.a,self.b)+'/'+str(self.job)+'/reauthorisations'
        self.assertEqual(self.client.post(url,json=self.renewal_document,headers=self.headers(scope=REQUEST_SCOPES)|{'X-OmniXat-Expected-Actor':str(self.user)}).status_code,404)
        other=uuid4(); self.request(self.document|{'job_id':str(other)})
        self.assertEqual(self.renew(self.renewal_document|{'job_id':str(other)}).status_code,409)
        self.assertEqual(self.rows('csv_extraction_requests'),2)
