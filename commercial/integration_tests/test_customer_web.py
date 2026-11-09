"""Customer pages, shared PostgreSQL services and real Chromium; fictional data."""
from contextlib import contextmanager
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from starlette.testclient import TestClient

from omnixat_core.customer_web import create_app
from omnixat_core.workspace_directory_postgres import list_workspaces
from test_identity_postgres import MembershipFixture


class CustomerWebFixture(MembershipFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.directory_role = cls.role+'_directory'
        password = uuid4().hex
        cls.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE').format(
            sql.Identifier(cls.directory_role),sql.Literal(password)))
        cls.owner.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_directory TO {}').format(sql.Identifier(cls.directory_role)))
        cls.owner.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_directory.list_workspaces(text,text,bigint,uuid,integer) TO {}').format(sql.Identifier(cls.directory_role)))
        cls.directory_dsn = make_conninfo(cls.admin.info.dsn,dbname=cls.database,user=cls.directory_role,password=password)
        def cleanup():
            cls.owner.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(cls.directory_role)))
            cls.admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(cls.directory_role)))
        cls.addClassCleanup(cleanup)


    def setUp(self):
        super().setUp()
        self.origin = 'https://workspace.example.test'
        @contextmanager
        def records():
            with psycopg.connect(self.runtime_dsn,autocommit=True,connect_timeout=2) as connection:
                yield connection
        @contextmanager
        def directory():
            with psycopg.connect(self.directory_dsn,autocommit=True,connect_timeout=2) as connection:
                yield connection
        self.records_factory, self.directory_factory = records,directory
        self.app = create_app(verifier=self.verifier,connection_factory=records,
                              directory_connection_factory=directory,public_origin=self.origin)
        self.client = TestClient(self.app,base_url=self.origin)
        self.addCleanup(self.client.close)
        self.base = '/v1/workspaces/'+self.a


    def headers(self, **changes):
        return {'X-Forwarded-Access-Token':self.token(**changes),'Origin':self.origin,'Sec-Fetch-Site':'same-origin'}


    def browser(self, token=None):
        """Gateway stand-in injects a generated token server-side; no API is mocked."""
        from playwright.sync_api import sync_playwright
        manager = sync_playwright().start()
        self.addCleanup(manager.stop)
        executable = os.environ.get('OMNIXAT_CHROMIUM_PATH')
        browser = manager.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
        self.addCleanup(browser.close)
        context = browser.new_context(viewport={'width':1440,'height':1000})
        self.gateway_token = token or self.token()
        def dispatch(route):
            request = route.request
            url = urlsplit(request.url)
            if url.scheme != 'https' or url.netloc != 'workspace.example.test':
                route.abort(); return
            headers = dict(request.all_headers())
            if url.path.startswith('/v1/'):
                headers['X-Forwarded-Access-Token'] = self.gateway_token
            response = self.client.request(request.method,url.path+('?' + url.query if url.query else ''),
                                           headers=headers,content=request.post_data_buffer)
            route.fulfill(status=response.status_code,headers=dict(response.headers),body=response.content)
        context.route('**/*',dispatch)
        page = context.new_page()
        errors = []
        page.on('pageerror',lambda error:errors.append(str(error)))
        return page,errors



class CustomerWebTests(CustomerWebFixture):
    def test_directory_returns_only_current_persisted_memberships_and_permissions(self):
        response = self.client.get('/v1/workspaces',headers=self.headers(role='owner',tenant_id=self.b))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['data'],{'items':[{'id':self.a,'display_name':'Fictional A','role':'editor','can_write':True}],'next_cursor':None})
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'viewer',NULL)",(self.b,self.user))
        page = self.client.get('/v1/workspaces?limit=1',headers=self.headers()).json()['data']
        second = self.client.get('/v1/workspaces?limit=1&after='+page['next_cursor'],headers=self.headers()).json()['data']
        self.assertEqual({item['id'] for item in page['items']+second['items']},{self.a,self.b})
        self.assertIsNone(second['next_cursor'])
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s',(self.b,))
        self.assertEqual(len(self.client.get('/v1/workspaces',headers=self.headers()).json()['data']['items']),1)
        self.owner.execute('UPDATE omnixat.identities SET disabled_at=now() WHERE id=%s',(self.user,))
        self.assertEqual(self.client.get('/v1/workspaces',headers=self.headers()).json()['data']['items'],[])


    def test_directory_rechecks_token_cutoff_scopes_and_clears_context(self):
        with self.directory_factory() as connection:
            result = list_workspaces(connection,self.verifier,self.token(),limit=1)
            self.assertEqual(result['items'][0]['id'],__import__('uuid').UUID(self.a))
            for setting in ['omnixat.tenant_id','omnixat.issuer','omnixat.subject','omnixat.directory_mode']:
                self.assertIn(connection.execute('SELECT current_setting(%s,true)',(setting,)).fetchone()[0],('',None))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute('SELECT * FROM omnixat.memberships')
            with self.assertRaises(PermissionError):
                list_workspaces(connection,self.verifier,self.token(scope='records:write'))
            self.owner.execute('UPDATE omnixat.identities SET tokens_valid_after=%s WHERE id=%s',(self.iat,self.user))
            self.assertEqual(list_workspaces(connection,self.verifier,self.token())['items'],[])
        with self.records_factory() as connection,self.assertRaises(PermissionError):
            list_workspaces(connection,self.verifier,self.token())


    def test_context_and_paged_records_are_tenant_and_parent_scoped(self):
        headers = self.headers()
        context = self.client.get(self.base+'/context',headers=headers).json()['data']
        self.assertEqual((context['role'],context['can_write']),('editor',True))
        for index in range(3):
            self.assertEqual(self.client.post(self.base+'/organisations',headers=headers,json={'display_name':f'Fictional {index}'}).status_code,201)
        first = self.client.get(self.base+'/organisations?limit=2',headers=headers).json()['data']
        second = self.client.get(self.base+'/organisations?limit=2&after='+first['next_cursor'],headers=headers).json()['data']
        self.assertEqual(len({row['id'] for row in first['items']+second['items']}),4)
        self.assertIsNone(second['next_cursor'])
        notes = self.client.get(self.base+f'/organisations/{self.org}/notes',headers=headers).json()['data']
        self.assertEqual(notes['items'][0]['body'],'Fictional evidence note')
        self.assertIn('created_at',notes['items'][0])
        other = self.client.post(self.base+'/organisations',headers=headers,json={'display_name':'Other organisation'}).json()['data']['id']
        self.assertEqual(self.client.get(self.base+f'/organisations/{other}/notes',headers=headers).json()['data']['items'],[])
        self.owner.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.b,self.user))
        other_base = '/v1/workspaces/'+self.b
        self.assertEqual(self.client.get(other_base+'/organisations',headers=headers).json()['data']['items'],[])
        self.assertEqual(self.client.get(other_base+f'/organisations/{self.org}/notes',headers=headers).status_code,404)
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE tenant_id=%s AND user_id=%s",(self.a,self.user))
        self.assertFalse(self.client.get(self.base+'/context',headers=headers).json()['data']['can_write'])
        self.assertEqual(self.client.post(self.base+'/organisations',headers=headers,json={'display_name':'Denied'}).status_code,403)
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user))
        self.assertEqual(self.client.get(self.base+'/organisations',headers=headers).status_code,403)


    def test_pagination_and_authentication_fail_closed(self):
        for query in ['limit=0','limit=51','limit=01','limit=true','limit=1&limit=2','after=invalid','after='+uuid4().hex,'unknown=1']:
            for path in ['/v1/workspaces',self.base+'/organisations',self.base+f'/organisations/{self.org}/notes']:
                with self.subTest(query=query,path=path):
                    self.assertEqual(self.client.get(path+'?'+query,headers=self.headers()).status_code,400)
        for headers in [{},{'X-Forwarded-User':'owner'},{'X-Forwarded-Access-Token':'invalid'},
                        [('X-Forwarded-Access-Token',self.token()),('X-Forwarded-Access-Token',self.token())],
                        self.headers()|{'Authorization':'Bearer '+self.token()}]:
            self.assertEqual(self.client.get('/v1/workspaces',headers=headers).status_code,401)
        self.assertEqual(self.client.get('/v1/workspaces',headers=self.headers(scope='records:write')).status_code,403)


    def test_origin_boundary_security_headers_and_asset_allowlist(self):
        headers = self.headers()
        for changed in [{k:v for k,v in headers.items() if k!='Origin'},headers|{'Origin':'https://attacker.example'},
                        headers|{'Origin':'null'},headers|{'Sec-Fetch-Site':'cross-site'},
                        list(headers.items())+[('Origin',self.origin)]]:
            self.assertEqual(self.client.post(self.base+'/organisations',headers=changed,json={'display_name':'Denied'}).status_code,403)
        response = self.client.get('/app')
        self.assertEqual(response.status_code,200)
        self.assertIn("script-src 'self'",response.headers['content-security-policy'])
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(response.headers['referrer-policy'],'no-referrer')
        self.assertNotIn(self.token(),response.text)
        self.assertEqual(self.client.get('/assets/app.js').status_code,200)
        self.assertEqual(self.client.get('/assets/site.css').status_code,200)
        self.assertEqual(self.client.get('/assets/requirements-http.txt').status_code,404)
        self.assertEqual(self.client.post('/app').status_code,405)
        self.assertEqual(self.client.get('/app',headers={'Host':'untrusted.example'}).status_code,400)
        for origin in ['http://workspace.example.test','https://workspace.example.test/','https://user@workspace.example.test','https://workspace.example.test:443']:
            with self.assertRaises(ValueError):
                create_app(verifier=self.verifier,connection_factory=self.records_factory,
                           directory_connection_factory=self.directory_factory,public_origin=origin)


    def test_directory_runs_with_non_bypass_migration_owner_and_forced_rls(self):
        from omnixat_core.postgres import MIGRATIONS
        name = 'directory_owner_'+uuid4().hex
        database = 'directory_test_'+uuid4().hex
        password = uuid4().hex
        self.admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE').format(sql.Identifier(name),sql.Literal(password)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP ROLE {}').format(sql.Identifier(name)))
        self.admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database),sql.Identifier(name)))
        self.addCleanup(self.admin.execute,sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
        owner_dsn = make_conninfo(self.admin.info.dsn,dbname=database,user=name,password=password)
        with psycopg.connect(owner_dsn,autocommit=True) as owner:
            for file in ['0001_tenant_records.sql','0002_identity_memberships.sql','0063_customer_workspace_directory.sql']:
                owner.execute((MIGRATIONS/file).read_text())
        with psycopg.connect(self.admin_dsn,dbname=database,autocommit=True) as admin:
            admin.execute("INSERT INTO omnixat.tenants VALUES (%s,'Fictional directory A'),(%s,'Fictional directory B')",(self.a,self.b))
            admin.execute("INSERT INTO omnixat.identities(id,issuer,subject,actor_kind) VALUES (%s,%s,%s,'human')",(self.user,self.issuer,self.subject))
            admin.execute("INSERT INTO omnixat.memberships VALUES (%s,%s,'editor',NULL)",(self.a,self.user))
            admin.execute(sql.SQL('GRANT USAGE ON SCHEMA omnixat_directory TO {}').format(sql.Identifier(self.directory_role)))
            admin.execute(sql.SQL('GRANT EXECUTE ON FUNCTION omnixat_directory.list_workspaces(text,text,bigint,uuid,integer) TO {}').format(sql.Identifier(self.directory_role)))
        with psycopg.connect(make_conninfo(self.directory_dsn,dbname=database),autocommit=True) as connection:
            result = list_workspaces(connection,self.verifier,self.token())
            self.assertEqual([str(item['id']) for item in result['items']],[self.a])
            self.assertEqual(result['items'][0]['display_name'],'Fictional directory A')

    def test_customer_startup_uses_pinned_keys_private_dsns_and_exclusive_admission(self):
        import json
        import tempfile
        from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
        from omnixat_core.customer_server import create_configured_app
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            public = self.key.public_key().public_bytes(Encoding.PEM,PublicFormat.SubjectPublicKeyInfo).decode()
            keys,records,directory = folder/'keys.json',folder/'records.dsn',folder/'directory.dsn'
            keys.write_text(json.dumps({'fictional':public}))
            records.write_text(self.runtime_dsn); directory.write_text(self.directory_dsn)
            records.chmod(0o600); directory.chmod(0o600)
            env = {'OMNIXAT_PUBLIC_ORIGIN':self.origin,'OMNIXAT_ACCESS_ISSUER':self.issuer,
                   'OMNIXAT_ACCESS_AUDIENCE':'omnixat-records','OMNIXAT_ACCESS_KEYS_FILE':str(keys),
                   'OMNIXAT_RECORD_DSN_FILE':str(records),'OMNIXAT_DIRECTORY_DSN_FILE':str(directory)}
            with patch.dict(os.environ,env):
                configured = create_configured_app()
                with TestClient(configured,base_url=self.origin) as client:
                    self.assertEqual(client.get('/v1/workspaces',headers=self.headers()).status_code,200)
                    self.assertEqual(client.get(self.base+'/context',headers=self.headers()).status_code,200)
                records.chmod(0o644)
                with self.assertRaises(ValueError):
                    create_configured_app()
