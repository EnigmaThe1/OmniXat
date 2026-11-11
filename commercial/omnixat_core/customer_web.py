"""Customer website and same-origin gateway boundary. No listener on import."""
from pathlib import Path
from urllib.parse import urlsplit
from starlette.responses import FileResponse, JSONResponse
from .http_api import create_app as create_records_app, Boundary

_ASSETS = Path(__file__).resolve().parents[1] / 'web'
_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def create_app(*, verifier, connection_factory, directory_connection_factory, public_origin, evidence_quarantine_dir=None, scan_status_connection_factory=None, scan_request_connection_factory=None, csv_review_connection_factory=None, csv_answer_connection_factory=None, csv_request_connection_factory=None, csv_request_status_connection_factory=None, expense_draft_connection_factory=None, expense_preparation_connection_factory=None, expense_funding_read_connection_factory=None, expense_funding_write_connection_factory=None, expense_journal_read_connection_factory=None, expense_journal_preview_connection_factory=None, expense_journal_write_connection_factory=None, journal_observation_connection_factory=None, bookkeeping_observation_connection_factory=None, correction_read_connection_factory=None, correction_write_connection_factory=None):
    origin = urlsplit(public_origin)
    if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
            or origin.path or origin.query or origin.fragment or origin.port not in (None,443)
            or public_origin != 'https://' + origin.hostname):
        raise ValueError('Canonical HTTPS public origin required')
    api = create_records_app(verifier=verifier,connection_factory=connection_factory,
                             directory_connection_factory=directory_connection_factory,allowed_hosts=[origin.hostname],
                             evidence_quarantine_dir=evidence_quarantine_dir,
                             scan_status_connection_factory=scan_status_connection_factory,
                             scan_request_connection_factory=scan_request_connection_factory,
                             csv_review_connection_factory=csv_review_connection_factory,
                             csv_answer_connection_factory=csv_answer_connection_factory,
                             csv_request_connection_factory=csv_request_connection_factory,
                             csv_request_status_connection_factory=csv_request_status_connection_factory,
                             expense_draft_connection_factory=expense_draft_connection_factory,
                             expense_preparation_connection_factory=expense_preparation_connection_factory,
                             expense_funding_read_connection_factory=expense_funding_read_connection_factory,
                             expense_funding_write_connection_factory=expense_funding_write_connection_factory,
                             expense_journal_read_connection_factory=expense_journal_read_connection_factory,
                             expense_journal_preview_connection_factory=expense_journal_preview_connection_factory,
                             expense_journal_write_connection_factory=expense_journal_write_connection_factory,
                             journal_observation_connection_factory=journal_observation_connection_factory,
                             bookkeeping_observation_connection_factory=bookkeeping_observation_connection_factory,
                             correction_read_connection_factory=correction_read_connection_factory,
                             correction_write_connection_factory=correction_write_connection_factory)

    async def application(scope, receive, send):
        if scope['type'] != 'http':
            await api(scope,receive,send)
            return
        async def secured_send(message):
            if message['type'] == 'http.response.start':
                message = dict(message,headers=list(message.get('headers',[]))+[
                    (b'content-security-policy',_CSP.encode()),(b'referrer-policy',b'no-referrer'),
                    (b'permissions-policy',b'camera=(), microphone=(), geolocation=()'),
                    (b'cross-origin-opener-policy',b'same-origin')])
            await send(message)
        path = scope['path']
        if path.startswith('/v1/'):
            headers = list(scope['headers'])
            forwarded = [v for k,v in headers if k.lower()==b'x-forwarded-access-token']
            authorization = [v for k,v in headers if k.lower()==b'authorization']
            if forwarded:
                if len(forwarded)!=1 or authorization or not 1 <= len(forwarded[0]) <= 16384:
                    await JSONResponse({'error':{'code':'authentication_required'}},status_code=401)(scope,receive,secured_send)
                    return
                headers = [(k,v) for k,v in headers if k.lower()!=b'x-forwarded-access-token']
                headers.append((b'authorization',b'Bearer '+forwarded[0]))
            if scope['method'] not in ('GET','HEAD','OPTIONS'):
                origins = [v.decode('latin1') for k,v in headers if k.lower()==b'origin']
                sites = [v for k,v in headers if k.lower()==b'sec-fetch-site']
                if origins != [public_origin] or any(value != b'same-origin' for value in sites):
                    await JSONResponse({'error':{'code':'origin_denied'}},status_code=403)(scope,receive,secured_send)
                    return
            await api(dict(scope,headers=headers),receive,secured_send)
            return
        assets = {'/assets/app.js':('app.js','text/javascript'),'/assets/site.css':('site.css','text/css')}
        if scope['method'] not in ('GET','HEAD'):
            response = JSONResponse({'error':{'code':'method_not_allowed'}},status_code=405,headers={'Allow':'GET, HEAD'})
        elif path in ('/','/app','/app/reauthenticated') or path.startswith('/app/workspaces/'):
            response = FileResponse(_ASSETS/'index.html',media_type='text/html')
        elif path in assets:
            filename,media = assets[path]
            response = FileResponse(_ASSETS/filename,media_type=media)
        else:
            response = JSONResponse({'error':{'code':'not_found'}},status_code=404)
        await response(scope,receive,secured_send)
    return Boundary(application,[origin.hostname])
