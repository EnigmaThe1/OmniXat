"""Exercise actual v0.4 UI in Chromium; synthetic data only."""
import importlib.util
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('household_ui_app',ROOT/'app.py')
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

with tempfile.TemporaryDirectory() as temp:
    core.DB=Path(temp)/'ui_test.sqlite3'
    core.init()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1540,'height':1040},device_scale_factor=1)
        js_errors=[]
        page.on('pageerror', lambda err:js_errors.append(str(err)))
        page.on('dialog',lambda dialog:dialog.accept())
        page.set_content((ROOT/'static/index.html').read_text())
        page.add_style_tag(content=(ROOT/'static/styles.css').read_text())
        def api_bridge(_,path,body):
            parsed=urlsplit(path)
            scope=parse_qs(parsed.query).get('scope',['all'])[0]
            with core.LOCK,core.connect() as db:
                if parsed.path=='/api/state':return core.state(db,scope)
                core.mutate(parsed.path,body or {},db)
                return core.state(db,scope if parsed.path!='/api/reset' else 'all')
        page.expose_binding('pyApi',api_bridge)
        page.evaluate('''window.fetch=async (path,opts={})=>{try{let body=opts.body?JSON.parse(opts.body):{};const v=await window.pyApi(path,body);return new Response(JSON.stringify(v),{status:200,headers:{'Content-Type':'application/json'}});}catch(e){return new Response(JSON.stringify({error:e.message}),{status:400,headers:{'Content-Type':'application/json'}});}}''')
        page.add_script_tag(content=(ROOT/'static/app.js').read_text())
        page.get_by_role('heading',name='Welcome back.').wait_for()
        assert page.locator('#scope-picker option').count() >= 6
        page.locator('button[data-page="people"]').click()
        page.get_by_role('heading',name='People & activities').wait_for()
        assert page.get_by_text('Alex Morgan (DEMO)',exact=True).count()>=1
        assert page.get_by_text('Sam Morgan (DEMO)',exact=True).count()>=1
        # Add independent fictional person.
        page.get_by_role('button',name='＋ Add person').first.click()
        page.locator('#name').fill('Taylor Example (DEMO)')
        page.get_by_role('button',name='Save',exact=True).click()
        page.locator('#page-view').get_by_text('Taylor Example (DEMO)',exact=True).wait_for()
        # Create independent self-employed activity, choose the newly added person.
        page.get_by_role('button',name='＋ Add self-employment activity').click()
        page.locator('#person_id').select_option(label='Taylor Example (DEMO)')
        page.locator('#name').fill('Fictional Landscape Work')
        page.get_by_role('button',name='Save',exact=True).click()
        page.locator('#page-view').get_by_text('Fictional Landscape Work',exact=True).wait_for()
        # Link same person to company already shared by two demo people.
        page.get_by_role('button',name='＋ Link person to company').click()
        page.locator('#person_id').select_option(label='Taylor Example (DEMO)')
        page.locator('#company_id').select_option(label='Northstar Studio Ltd (DEMO)')
        page.locator('#role').select_option('director')
        page.get_by_role('button',name='Save',exact=True).click()
        # Switch context to Taylor, create a tax year independent of both other people.
        page.locator('#scope-picker').select_option(label='Taylor Example (DEMO)')
        page.get_by_text('Current selection:').wait_for()
        page.locator('button[data-page="tax"]').click()
        page.get_by_role('button',name='＋ Add / edit personal tax year').click()
        page.locator('#person_id').select_option(label='Taylor Example (DEMO)')
        page.locator('#start_year').fill('2025')
        page.get_by_role('button',name='Save',exact=True).click()
        page.locator('#page-view').get_by_text('Taylor Example (DEMO) · 2025–26').wait_for()
        # Record status for that person only.
        page.locator('button[data-page="filings"]').click()
        page.get_by_role('button',name='＋ Record return status').click()
        page.locator('#kind').select_option('self_assessment')
        page.locator('#period_key').fill('2025-26')
        page.locator('#status').select_option('reported_submitted')
        page.locator('#evidence').fill('DEMO-FAKE-FILING-001')
        page.get_by_role('button',name='Save',exact=True).click()
        page.locator('#page-view').get_by_text('DEMO-FAKE-FILING-001').wait_for()
        page.screenshot(path=str(ROOT/'omnixat_v04_filings.png'),full_page=True)
        # Switch to Sam and ensure Taylor filing is hidden; no mixing of personal data.
        page.locator('#scope-picker').select_option(label='Sam Morgan (DEMO)')
        page.locator('#page-view').get_by_text('No filing statuses recorded for this view.').wait_for()
        assert page.locator('#page-view').get_by_text('DEMO-FAKE-FILING-001').count() == 0
        page.locator('button[data-page="calendar"]').click()
        page.get_by_role('heading',name='Tax calendar').wait_for()
        assert page.locator('.cal-entry').count()==0
        page.locator('#scope-picker').select_option(label='Taylor Example (DEMO)')
        page.locator('.cal-entry').first.wait_for()
        assert 'Taylor Example (DEMO)' in page.locator('#page-view').inner_text()
        page.screenshot(path=str(ROOT/'omnixat_v04_person_calendar.png'),full_page=True)
        page.locator('#scope-picker').select_option('all')
        page.locator('button[data-page="people"]').click()
        page.screenshot(path=str(ROOT/'omnixat_v04_people.png'),full_page=True)
        assert not js_errors,js_errors
        browser.close()
print('HOUSEHOLD GUI PASS: add person/activity, company link, personal tax year, filing evidence, selector scoping and screenshots')
