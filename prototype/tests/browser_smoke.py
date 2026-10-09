"""Regression GUI: original dashboard/forms/calendars with v0.4 entity-aware bridge."""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('demo_smoke',ROOT/'app.py')
app=importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

with tempfile.TemporaryDirectory() as tmp:
    app.DB=Path(tmp)/'ui-regression.sqlite3'
    app.init()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        pg=browser.new_page(viewport={'width':1440,'height':950},device_scale_factor=1)
        errors=[]
        pg.on('pageerror',lambda err:errors.append(str(err)))
        pg.set_content((ROOT/'static/index.html').read_text())
        pg.add_style_tag(content=(ROOT/'static/styles.css').read_text())
        def bridge(_,path,body):
            parsed=urlsplit(path)
            scope=parse_qs(parsed.query).get('scope',['all'])[0]
            with app.LOCK,app.connect() as c:
                if parsed.path=='/api/state':return app.state(c,scope)
                app.mutate(parsed.path,body or {},c)
                return app.state(c,scope if parsed.path!='/api/reset' else 'all')
        pg.expose_binding('pyApi',bridge)
        pg.evaluate('''window.fetch=async function(path,options={}){
            try{const data=options.body?JSON.parse(options.body):{};const result=await window.pyApi(path,data);
                 return new Response(JSON.stringify(result),{status:200,headers:{'Content-Type':'application/json'}});}
            catch(e){return new Response(JSON.stringify({error:e.message}),{status:400,headers:{'Content-Type':'application/json'}});}
        };''')
        pg.add_script_tag(content=(ROOT/'static/app.js').read_text())
        pg.get_by_role('heading',name='Welcome back.').wait_for()
        assert pg.locator('.stat-num').first.inner_text()=='1'
        pg.screenshot(path=str(ROOT/'omnixat_dashboard.png'),full_page=True)
        pg.locator('button[data-page="companies"]').click()
        pg.get_by_role('heading',name='Your companies').wait_for()
        pg.get_by_role('button',name='＋ Add company').first.click()
        pg.locator('#name').fill('Sample Demo Company')
        pg.locator('#number').fill('MOCK9999')
        pg.get_by_role('button',name='Save',exact=True).click()
        pg.locator('#page-view').get_by_text('Sample Demo Company',exact=True).wait_for()
        pg.locator('button[data-page="questions"]').click()
        pg.locator('button[data-answer="income"][data-value="yes"]').click()
        pg.get_by_text('✓ Saved answer: yes').wait_for()
        assert pg.locator('#question-count').inner_text()=='15'
        pg.locator('button[data-page="tasks"]').click()
        pg.get_by_role('button',name='＋ New task').click()
        pg.locator('#title').fill('Review made-up tax checklist')
        pg.locator('#due').fill('2027-02-01')
        pg.get_by_role('button',name='Save',exact=True).click()
        pg.get_by_text('Review made-up tax checklist',exact=True).wait_for()
        pg.locator('label.task-row').filter(has_text='Review made-up tax checklist').locator('input').check()
        assert pg.locator('label.task-row').filter(has_text='Review made-up tax checklist').locator('input').is_checked()
        pg.locator('button[data-page="calendar"]').click()
        pg.get_by_role('heading',name='Tax calendar').wait_for()
        assert pg.locator('a[download="omnixat-demo-calendar.ics"]').count()==1
        pg.screenshot(path=str(ROOT/'omnixat_calendar.png'),full_page=True)
        assert not errors,errors
        browser.close()
print('BROWSER REGRESSION PASS: dashboard, companies, questions, tasks, calendar and screenshots')
