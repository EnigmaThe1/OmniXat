"""Real Chromium + real ASGI/PostgreSQL, with a server-side gateway stand-in."""
import os
from pathlib import Path
from unittest.mock import patch
from test_customer_web import CustomerWebFixture


class CustomerWorkspaceBrowserTests(CustomerWebFixture):
    def test_chromium_customer_create_note_reload_xss_and_mobile(self):
        from playwright.sync_api import expect
        page,errors = self.browser()
        page.goto(self.origin+'/app')
        expect(page.get_by_role('heading',name='Everything starts here.')).to_be_visible()
        page.get_by_role('button',name='+ New organisation').click()
        page.get_by_label('Organisation name',exact=True).fill('Fictional Studio Ltd')
        page.get_by_role('button',name='Create organisation',exact=True).click()
        expect(page.get_by_role('heading',name='Fictional Studio Ltd',exact=True)).to_be_visible()
        page.get_by_label('Note',exact=True).fill('Fictional invoice context\n<script>window.untrusted = true</script>')
        page.get_by_role('button',name='← All organisations').click()
        expect(page.get_by_role('heading',name='Fictional Studio Ltd',exact=True)).to_be_visible()
        expect(page.get_by_role('status').filter(has_text='Save or clear the note')).to_be_visible()
        page.get_by_role('button',name='Save note',exact=True).click()
        expect(page.get_by_role('status').filter(has_text='Note saved.')).to_be_visible()
        page.reload()
        expect(page.locator('#notes')).to_contain_text('<script>window.untrusted = true</script>')
        self.assertIsNone(page.evaluate('window.untrusted'))
        self.assertEqual(page.evaluate('Object.keys(localStorage).length + Object.keys(sessionStorage).length'),0)
        page.get_by_role('button',name='← All organisations').click()
        expect(page.get_by_role('heading',name='Everything starts here.')).to_be_visible()
        page.get_by_role('searchbox',name='Filter loaded organisations').fill('Fictional Studio')
        expect(page.locator('#organisations li')).to_have_count(1)
        artifacts = os.environ.get('OMNIXAT_BROWSER_ARTIFACTS')
        if artifacts:
            Path(artifacts).mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(Path(artifacts)/'customer-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        expect(page.get_by_role('heading',name='Everything starts here.')).to_be_visible()
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        if artifacts:
            page.screenshot(path=str(Path(artifacts)/'customer-mobile.png'),full_page=True)
        self.assertEqual(errors,[])


    def test_chromium_viewer_revocation_and_uncertain_save_retry(self):
        from playwright.sync_api import expect
        page,errors = self.browser()
        page.goto(self.origin+f'/app/workspaces/{self.a}/organisations/{self.org}')
        expect(page.get_by_role('heading',name='Fictional organisation',exact=True)).to_be_visible()
        page.get_by_label('Note',exact=True).fill('Fictional retry note')
        from omnixat_core.postgres import TenantRecords
        original = TenantRecords.create_note
        calls = []
        def fail_after_first_commit(*args,**kwargs):
            result = original(*args,**kwargs)
            calls.append(result['id'])
            return result
        # A response is lost after the real database transaction has committed.
        base_request = self.client.request
        lost = [False]
        def lose_response(method,url,**kwargs):
            response = base_request(method,url,**kwargs)
            if method == 'POST' and str(url).endswith('/notes') and not lost[0]:
                lost[0] = True
                import httpx
                return httpx.Response(503,json={'error':{'code':'service_unavailable'}})
            return response
        with patch.object(TenantRecords,'create_note',side_effect=None,autospec=True) as method:
            method.side_effect = fail_after_first_commit
            with patch.object(self.client,'request',side_effect=lose_response):
                page.get_by_role('button',name='Save note',exact=True).click()
                expect(page.get_by_role('button',name='Retry save',exact=True)).to_be_visible()
                expect(page.get_by_label('Note',exact=True)).to_be_disabled()
                page.get_by_role('button',name='Retry save',exact=True).click()
                expect(page.get_by_role('status').filter(has_text='Note saved.')).to_be_visible()
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0],calls[1])
        self.assertEqual(self.owner.execute("SELECT count(*) FROM omnixat.notes WHERE tenant_id=%s AND body='Fictional retry note'",(self.a,)).fetchone(),(1,))
        self.owner.execute("UPDATE omnixat.memberships SET role='viewer' WHERE tenant_id=%s AND user_id=%s",(self.a,self.user))
        page.reload()
        expect(page.locator('#notes')).to_contain_text('Fictional retry note')
        expect(page.locator('#note-form')).to_be_hidden()
        self.owner.execute('UPDATE omnixat.memberships SET revoked_at=now() WHERE tenant_id=%s AND user_id=%s',(self.a,self.user))
        page.reload()
        expect(page.get_by_role('alert')).to_contain_text('Your access has changed')
        expect(page.locator('#content')).to_be_hidden()
        self.assertEqual(errors,[])
