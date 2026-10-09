"""Interactive Chromium smoke test: run `python tests/browser_smoke.py` (requires playwright)."""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen
import importlib.util
import json
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
with tempfile.TemporaryDirectory() as tmp:
    env=dict(os.environ, OMNIXAT_DEMO_DB=str(Path(tmp)/'browser.sqlite3'))
    proc=subprocess.Popen([sys.executable,'app.py','--port','18765'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for n in range(50):
            try:
                urlopen('http://127.0.0.1:18765/api/health',timeout=0.3).close()
                break
            except Exception:
                time.sleep(.1)
        else:
            raise RuntimeError('Local prototype did not start')
        # Managed Chromium blocks localhost navigation here. Exercise the *exact* UI files
        # with in-memory HTTP API bridge, while test_demo.py separately covers real HTTP.
        spec=importlib.util.spec_from_file_location('demo_browser_app',ROOT/'app.py')
        core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
        core.DB=Path(tmp)/'browser.sqlite3'
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':950},device_scale_factor=1)
            page.on('pageerror',lambda e:print('JS ERROR:',e))
            html=(ROOT/'static/index.html').read_text()
            page.set_content(html)
            page.add_style_tag(content=(ROOT/'static/styles.css').read_text())
            def api_bridge(_,path,body):
                with core.LOCK,core.connect() as conn:
                    if path=='/api/state':return core.state(conn)
                    core.mutate(path,body or {},conn)
                    return core.state(conn)
            page.expose_binding('pyApi',api_bridge)
            page.evaluate("""window.fetch = async function(path, options={}) {
                const body = options.body ? JSON.parse(options.body) : null;
                try { const result = await window.pyApi(path, body); return new Response(JSON.stringify(result), {status:200,headers:{'Content-Type':'application/json'}}); }
                catch(err) { return new Response(JSON.stringify({error:err.message}), {status:400,headers:{'Content-Type':'application/json'}}); }
            };""")
            page.add_script_tag(content=(ROOT/'static/app.js').read_text())
            page.get_by_role('heading',name='Welcome back.').wait_for()
            assert page.locator('.stat-num').first.inner_text() == '1'
            page.screenshot(path=str(ROOT/'omnixat_dashboard.png'),full_page=True)

            page.locator('button[data-page="companies"]').click()
            page.get_by_role('heading',name='Your companies').wait_for()
            page.get_by_role('button',name='＋ Add a company').click()
            page.locator('#name').fill('Sample Demo Company')
            page.locator('#number').fill('MOCK9999')
            page.get_by_role('button',name='Save',exact=True).click()
            page.get_by_text('Sample Demo Company',exact=True).wait_for()
            assert page.get_by_text('Not verified').count()>=1

            page.locator('button[data-page="questions"]').click()
            page.locator('button[data-answer="income"][data-value="yes"]').click()
            page.get_by_text('✓ Saved answer: yes').wait_for()
            assert page.locator('#question-count').inner_text() == '3'

            page.locator('button[data-page="tasks"]').click()
            page.get_by_role('button',name='＋ New task').click()
            page.locator('#title').fill('Review made-up tax checklist')
            page.locator('#due').fill('2027-02-01')
            page.get_by_role('button',name='Save',exact=True).click()
            page.get_by_text('Review made-up tax checklist',exact=True).wait_for()
            page.locator('label.task-row').filter(has_text='Review made-up tax checklist').locator('input').check()
            page.locator('label.task-row').filter(has_text='Review made-up tax checklist').locator('input').is_checked()

            page.locator('button[data-page="calendar"]').click()
            page.get_by_role('heading',name='Tax calendar').wait_for()
            assert page.locator('a[download="omnixat-demo-calendar.ics"]').count()==1
            page.screenshot(path=str(ROOT/'omnixat_calendar.png'),full_page=True)
            browser.close()
        print('BROWSER SMOKE: PASS — dashboard, add company, answer question, add/complete task, calendar export link')
    finally:
        proc.terminate()
        try:proc.wait(timeout=4)
        except subprocess.TimeoutExpired:proc.kill()
