"""Browser Lab browser-GUI integration test with the real HTTP backend.

On this hosted environment Chromium network navigation to loopback is blocked.
The dashboard runs in a real Chromium DOM with a Python HTTP bridge; the
backend separately runs a second real Chromium instance for the practice portal.
"""
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    soc=socket.socket();soc.bind(('127.0.0.1',0));port=soc.getsockname()[1];soc.close()
    base=f'http://127.0.0.1:{port}'
    proc=subprocess.Popen([sys.executable,str(ROOT/'app.py'),'--port',str(port)],cwd=ROOT,
                          env=dict(os.environ,OMNIXAT_DEMO_DB=str(Path(tmp)/'demo.sqlite3')),
                          stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for _ in range(90):
            try:
                urlopen(base+'/api/health',timeout=.2).close();break
            except Exception:time.sleep(.1)
        else: raise RuntimeError('server startup failed')
        def bridge(_,path,data):
            if path=='/api/state':
                with urlopen(base+path,timeout=30) as resp:return json.load(resp)
            req=Request(base+path,method='POST',data=json.dumps(data).encode(),headers={
                'Content-Type':'application/json','X-OmniXat-Demo':'1'})
            with urlopen(req,timeout=50) as resp:return json.load(resp)
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
            pg=browser.new_page(viewport={'width':1440,'height':1080})
            errors=[]
            pg.on('pageerror',lambda error:errors.append(str(error)))
            pg.on('dialog',lambda dialog:dialog.accept())
            pg.set_content((ROOT/'static/index.html').read_text())
            pg.add_style_tag(content=(ROOT/'static/styles.css').read_text())
            pg.expose_binding('pyApi',bridge)
            pg.evaluate("""(() => {window.fetch=async function(path,options={}) {
              try {
                const data=options.body ? JSON.parse(options.body):{};
                const result=await window.pyApi(path,data);
                return new Response(JSON.stringify(result),{status:200,headers:{'Content-Type':'application/json'}});
              }catch(e){return new Response(JSON.stringify({error:e.message}),{status:400,headers:{'Content-Type':'application/json'}});}
            };})()""")
            pg.add_script_tag(content=(ROOT/'static/app.js').read_text())
            pg.get_by_role('heading',name='Welcome back.').wait_for()
            pg.locator('button[data-page="browser"]').click()
            pg.get_by_role('heading',name='Browser Lab').wait_for()
            pg.locator('#browser-company').fill('Synthetic Browser Trial Ltd')
            pg.locator('#browser-period').fill('2027-03-31')
            pg.locator('#browser-amount').fill('1875.20')
            pg.locator('#browser-fictional').check()
            pg.get_by_role('button',name='▶ Inspect and prepare with Playwright').click()
            pg.get_by_text('awaiting approval',exact=True).wait_for(timeout=45000)
            assert pg.get_by_text('Synthetic Browser Trial Ltd',exact=True).count()>=1
            assert pg.get_by_text('Read the review page and verified every field matches the input').count()==1
            with urlopen(base+'/api/browser/preview') as resp: preview=base64.b64encode(resp.read()).decode()
            pg.locator('.browser-preview').evaluate('(el,data)=>el.src="data:image/png;base64,"+data',preview)
            pg.screenshot(path=str(ROOT/'omnixat_browser_lab_review.png'),full_page=True)
            pg.get_by_role('button',name='Approve DEMO submission →').click()
            pg.get_by_text('demo submitted',exact=True).wait_for(timeout=45000)
            assert 'DEMO-' in pg.locator('.browser-receipt').inner_text()
            with urlopen(base+'/api/browser/preview') as resp: preview=base64.b64encode(resp.read()).decode()
            pg.locator('.browser-preview').evaluate('(el,data)=>el.src="data:image/png;base64,"+data',preview)
            pg.screenshot(path=str(ROOT/'omnixat_browser_lab_submitted.png'),full_page=True)
            assert not errors, errors
            browser.close()
        print('BROWSER LAB UI PASS: actual GUI inputs, real backend, Chromium practice workflow, approval, receipt and screenshots')
    finally:
        proc.terminate()
        try:proc.wait(timeout=4)
        except subprocess.TimeoutExpired:proc.kill()
