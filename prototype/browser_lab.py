"""Playwright-only local test portal driver. Zero live government/browser automation.

Strictly local fixture at /demo-portal. Server never accepts an external URL,
DOM selector, script, model-provided action or credentials from a client.
"""
from __future__ import annotations

import os
import json
import shutil
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit


def available() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


def normalise(data: dict) -> dict:
    company = data.get('company')
    period = data.get('period')
    amount = data.get('amount')
    if not isinstance(company, str) or not 3 <= len(company.strip()) <= 70:
        raise ValueError('Enter a fictional company name (3–70 characters).')
    if not isinstance(period, str) or not period.startswith(('2026-', '2027-', '2028-')):
        raise ValueError('Use a fictional period ending in 2026, 2027 or 2028.')
    from datetime import date
    try:
        date.fromisoformat(period)
    except (ValueError, TypeError) as exc:
        raise ValueError('Enter a valid ISO accounting period end.') from exc
    if not isinstance(amount, str):
        raise ValueError('The sample amount must be typed as a decimal string.')
    try:
        decimal = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError('Enter a valid sample amount.') from exc
    if not decimal.is_finite() or decimal < 0 or decimal > 99999999 or decimal.as_tuple().exponent < -2:
        raise ValueError('Use a non-negative fictional amount with at most two decimal places.')
    return {'company': company.strip(), 'period': period, 'amount': format(decimal, '.2f')}


def execute(*, port: int, run_id: str, payload: dict, submit: bool = False, offline_submit=None) -> dict:
    """Open a real Chromium page, fill a local form, and optionally submit a demo record.

    Fresh isolated context per call. Requests are denied except for the fixed
    loopback origin. Always closes the browser. No screenshots in logs.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError('Playwright is not installed. Run: pip install playwright && python -m playwright install chromium') from exc

    if not (0 < int(port) < 65536):
        raise ValueError('Invalid local port')
    payload = normalise(payload)
    portal = f'http://127.0.0.1:{port}/demo-portal?run_id={run_id}'
    origin = f'http://127.0.0.1:{port}'
    steps = []
    with sync_playwright() as pw:
        chrome = os.getenv('OMNIXAT_CHROMIUM_PATH', '').strip() or shutil.which('chromium') or shutil.which('google-chrome')
        try:
            browser = pw.chromium.launch(headless=True, **({'executable_path': chrome} if chrome else {}))
        except Exception as exc:
            raise RuntimeError('Chromium is unavailable; install the Playwright Chromium browser or set OMNIXAT_CHROMIUM_PATH.') from exc
        try:
            context = browser.new_context(accept_downloads=False, service_workers='block', viewport={'width': 1100, 'height': 790})
            def route_request(route):
                url = urlsplit(route.request.url)
                if url.scheme == 'http' and url.hostname == '127.0.0.1' and url.port == port:
                    route.continue_()
                else:
                    route.abort()
            context.route('**/*', route_request)
            page = context.new_page()
            page.set_default_timeout(9000)
            from playwright.sync_api import Error as PlaywrightError
            try:
                page.goto(portal, wait_until='domcontentloaded', timeout=9000)
                steps.append('Navigated Chromium to the allowlisted local practice portal')
            except PlaywrightError as exc:
                if 'ERR_BLOCKED_BY_ADMINISTRATOR' not in str(exc):
                    raise
                # Some hosted execution environments prohibit ALL Chromium loopback
                # navigation. Exercise the same exact local HTML, CSS and JS in a
                # Chromium page using an in-memory fixture instead. No external I/O.
                # The user's normal Ubuntu install should use the real URL path.
                root = Path(__file__).resolve().parent / 'static'
                if offline_submit is None and submit:
                    raise RuntimeError('Fixture browser networking blocked and no local receipt callback.')
                page.close()
                page = context.new_page()
                page.set_default_timeout(9000)
                page.set_content((root / 'demo-portal.html').read_text(), wait_until='domcontentloaded')
                page.add_style_tag(content=(root / 'demo-portal.css').read_text())
                if submit:
                    page.expose_binding('localDemoSubmit', lambda source, body: offline_submit(body))
                    page.evaluate("""(() => { window.fetch=async function(url, options={}) {
                        if(url !== '/api/demo-portal/submissions') throw Error('Only the local demo endpoint is allowed');
                        const result = await window.localDemoSubmit(JSON.parse(options.body));
                        return new Response(JSON.stringify(result), {status:200,headers:{'Content-Type':'application/json'}});
                    }; })()""")
                page.evaluate('(id) => { window.fixtureRunId = id; }', run_id)
                page.add_script_tag(content=(root / 'demo-portal.js').read_text())
                steps.append('Opened the exact local practice page in Chromium (offline fixture mode; host blocked navigation)')
            assert page.title() == 'OmniXat · Practice Filing Portal' 
            page.get_by_label('Company name').fill(payload['company'])
            page.get_by_label('Accounting period end').fill(payload['period'])
            page.get_by_label('Demo amount in pounds').fill(payload['amount'])
            steps.append('Filled company, accounting period and sample amount using accessible form labels')
            page.get_by_role('button', name='Review demo record').click()
            review = page.locator('#review-section')
            review.wait_for(state='visible')
            verified = [
                page.locator('#review-company').inner_text() == payload['company'],
                page.locator('#review-period').inner_text() == payload['period'],
                page.locator('#review-amount').inner_text() == payload['amount'],
            ]
            if not all(verified):
                raise RuntimeError('Page review differs from the requested fictitious data.')
            steps.append('Read the review page and verified every field matches the input')
            status = 'awaiting_approval'
            receipt = None
            if submit:
                page.get_by_role('button', name='Submit demo record').click()
                page.locator('#receipt-section').wait_for(state='visible', timeout=9000)
                receipt = page.locator('#receipt-id').inner_text().strip()
                if not receipt.startswith('DEMO-'):
                    raise RuntimeError('Local practice portal did not return a demo receipt.')
                steps.append('Clicked Submit demo record after approval and verified the local-only receipt')
                status = 'demo_submitted'
            screenshot = page.screenshot(type='png', full_page=True, animations='disabled')
            context.close()
            return {'status': status, 'receipt': receipt, 'steps': steps, 'screenshot': screenshot}
        finally:
            browser.close()
