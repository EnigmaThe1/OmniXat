"""Development ASGI records transport; no server starts on import.

Server-owned verifier and bounded exclusive connection factory are mandatory.
Bearer only: no cookies, role headers, browser login or filing/approval endpoints.
"""
import json
import re
from uuid import UUID, uuid4
from datetime import datetime
from urllib.parse import urlsplit

import anyio
import psycopg
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .identity import AuthenticationError
from .identity_postgres import authenticated_records
from .postgres import CreationConflict, validate_creation_key

MAX_BODY_BYTES = 32768
BODY_TIMEOUT_SECONDS = 5


class ApiError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def expected_actor(request, *, writing):
    """Optional continuity constraint; it can restrict but never grant authority."""
    values = request.headers.getlist('x-omnixat-expected-actor')
    if not values:
        return None
    if not writing:
        raise ApiError(400, 'unsupported_parameter')
    try:
        if len(values) != 1 or str(UUID(values[0])) != values[0]:
            raise ValueError()
    except ValueError:
        raise ApiError(400, 'invalid_expected_actor') from None
    return values[0]


def error_response(scope, status, code):
    headers = {'WWW-Authenticate': 'Bearer'} if status == 401 else None
    return JSONResponse({'error': {'code': code}, 'request_id': scope['request_id']},
                        status_code=status, headers=headers)


def _reject_constant(value):
    raise ValueError('Nonfinite JSON value')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


async def _payload(request, field, maximum):
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'application/json':
        raise ApiError(415, 'unsupported_media_type')
    if request.headers.get('content-encoding', 'identity').lower() != 'identity':
        raise ApiError(415, 'unsupported_media_type')
    lengths = request.headers.getlist('content-length')
    if lengths:
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            raise ApiError(400, 'invalid_request')
        if len(lengths[0]) > 10 or int(lengths[0]) > MAX_BODY_BYTES:
            raise ApiError(413, 'body_too_large')
    body = bytearray()
    try:
        with anyio.fail_after(BODY_TIMEOUT_SECONDS):
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_BODY_BYTES:
                    raise ApiError(413, 'body_too_large')
                body.extend(chunk)
    except TimeoutError:
        raise ApiError(408, 'request_timeout') from None
    try:
        document = json.loads(body.decode('utf-8'), object_pairs_hook=_pairs,
                              parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ApiError(400, 'invalid_json') from None
    if (not isinstance(document, dict) or set(document) != {field}
            or not isinstance(document[field], str) or not document[field].strip()
            or len(document[field]) > maximum or '\x00' in document[field]):
        raise ApiError(422, 'invalid_fields')
    try:
        document[field].encode('utf-8')
    except UnicodeEncodeError:
        raise ApiError(422, 'invalid_fields') from None
    return document[field]


class Boundary:
    """Consistent host/TLS checks, cache prevention and server-generated request IDs."""
    def __init__(self, app, allowed_hosts):
        self.app, self.allowed_hosts = app, frozenset(h.lower() for h in allowed_hosts)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        scope = dict(scope, request_id=str(uuid4()))
        request = Request(scope)
        async def safe_send(message):
            if message['type'] == 'http.response.start':
                message = dict(message)
                message['headers'] = list(message.get('headers', [])) + [
                    (b'cache-control', b'no-store'), (b'pragma', b'no-cache'),
                    (b'x-content-type-options', b'nosniff'),
                    (b'x-request-id', scope['request_id'].encode('ascii'))]
            await send(message)
        hosts = request.headers.getlist('host')
        try:
            host = hosts[0] if len(hosts) == 1 else ''
            parsed = urlsplit('//' + host)
            valid_host = (bool(host) and not any(c in host for c in '/\\@?#')
                          and parsed.hostname in self.allowed_hosts
                          and (parsed.port is None or 1 <= parsed.port <= 65535))
        except ValueError:
            valid_host = False
        if not valid_host:
            await error_response(scope, 400, 'invalid_host')(scope, receive, safe_send)
        elif scope.get('scheme') != 'https':
            await error_response(scope, 400, 'https_required')(scope, receive, safe_send)
        else:
            await self.app(scope, receive, safe_send)


def create_app(*, verifier, connection_factory, allowed_hosts, directory_connection_factory=None, evidence_quarantine_dir=None, scan_status_connection_factory=None, scan_request_connection_factory=None):
    """Return ASGI app only. Factory must bound acquisition and lease exclusively."""
    if (not isinstance(allowed_hosts, (list, tuple)) or not allowed_hosts
            or any(not isinstance(h, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', h)
                   for h in allowed_hosts)):
        raise ValueError('Explicit DNS/IPv4 hosts required; wildcards are not allowed')
    if not callable(connection_factory):
        raise ValueError('Server-owned connection factory required')

    def operate(token, tenant, action, object_id, value, key, page, expected):
        try:
            if action == 'list_workspaces':
                from .workspace_directory_postgres import list_workspaces
                with directory_connection_factory() as connection:
                    return list_workspaces(connection,verifier,token,**page)
            with connection_factory() as connection:
                with authenticated_records(connection, verifier, token, tenant,
                                           write=action.startswith('create')) as records:
                    if expected is not None and records._actor.user_id != expected:
                        raise ApiError(409, 'session_changed')
                    if action == 'workspace_context':
                        context = records.workspace_context()
                        context['actor_id'] = records._actor.user_id
                        scopes = verifier.verify(token).scopes
                        context['evidence_access'] = evidence_quarantine_dir is not None and 'evidence:read' in scopes
                        context['scan_status_access'] = (context['evidence_access']
                            and scan_status_connection_factory is not None)
                        context['can_request_scan'] = (context['scan_status_access'] and scan_request_connection_factory is not None
                            and context['can_write'] and records._actor.actor_kind == 'human' and 'evidence:scan' in scopes)
                        context['can_upload_evidence'] = (context['evidence_access'] and context['can_write']
                            and records._actor.actor_kind == 'human' and 'evidence:register' in scopes)
                        return context
                    if action == 'list_organisations':
                        return records.list_organisations(**page)
                    if action == 'list_notes':
                        return records.list_notes(object_id,**page)
                    if action == 'create_organisation':
                        return records.create_organisation(value, idempotency_key=key)
                    if action == 'get_organisation':
                        return records.get_organisation(object_id)
                    if action == 'create_note':
                        return records.create_note(object_id, value, idempotency_key=key)
                    return records.get_note(object_id)
        except AuthenticationError:
            raise ApiError(403, 'access_denied') from None
        except PermissionError:
            raise ApiError(403, 'access_denied') from None
        except CreationConflict:
            raise ApiError(409, 'idempotency_conflict') from None
        except KeyError:
            raise ApiError(404, 'not_found') from None
        except (psycopg.OperationalError, TimeoutError):
            raise ApiError(503, 'service_unavailable') from None
        except psycopg.errors.CheckViolation:
            raise ApiError(422, 'invalid_fields') from None

    async def endpoint(request):
        try:
            headers = request.headers.getlist('authorization')
            parts = headers[0].split(' ') if len(headers) == 1 and len(headers[0]) <= 16400 else []
            if len(parts) != 2 or parts[0].lower() != 'bearer' or not parts[1]:
                raise ApiError(401, 'authentication_required')
            token = parts[1]
            try:
                verifier.verify(token)
            except AuthenticationError:
                raise ApiError(401, 'invalid_token') from None
            action = request.scope['endpoint'].action
            expected = expected_actor(request, writing=action.startswith('create'))
            page = {}
            if action.startswith('list_'):
                pairs = list(request.query_params.multi_items())
                if any(key not in ('after','limit') for key,value in pairs) or len(dict(pairs)) != len(pairs):
                    raise ApiError(400,'unsupported_parameter')
                try:
                    if 'after' in request.query_params:
                        raw = request.query_params['after']
                        page['after'] = str(UUID(raw))
                        if page['after'] != raw:
                            raise ValueError()
                    raw_limit = request.query_params.get('limit','50')
                    if not re.fullmatch(r'[1-9][0-9]?',raw_limit) or not 1 <= int(raw_limit) <= 50:
                        raise ValueError()
                    page['limit'] = int(raw_limit)
                except ValueError:
                    raise ApiError(400,'invalid_page') from None
            elif request.query_params:
                raise ApiError(400,'unsupported_parameter')
            try:
                tenant = str(UUID(request.path_params['tenant'])) if 'tenant' in request.path_params else None
                object_id = str(UUID(request.path_params['object_id'])) if 'object_id' in request.path_params else None
            except ValueError:
                raise ApiError(400, 'invalid_identifier') from None
            keys = request.headers.getlist('idempotency-key')
            if keys and not action.startswith('create'):
                raise ApiError(400, 'unsupported_parameter')
            try:
                if len(keys) > 1:
                    raise ValueError("Duplicate creation key")
                key = validate_creation_key(keys[0] if keys else None)
            except ValueError:
                raise ApiError(400, 'invalid_idempotency_key') from None
            value = None
            if action == 'create_organisation':
                value = await _payload(request, 'display_name', 200)
            elif action == 'create_note':
                value = await _payload(request, 'body', 10000)
            result = await run_in_threadpool(operate, token, tenant, action, object_id, value, key, page, expected)
            def serialise(value):
                if isinstance(value,UUID):
                    return str(value)
                if isinstance(value,datetime):
                    return value.isoformat()
                if isinstance(value,dict):
                    return {key:serialise(item) for key,item in value.items()}
                if isinstance(value,list):
                    return [serialise(item) for item in value]
                return value
            data = serialise(result)
            return JSONResponse({'data': data, 'request_id': request.scope['request_id']},
                                status_code=201 if action.startswith('create') else 200)
        except ApiError as exc:
            return error_response(request.scope, exc.status, exc.code)
        except Exception:
            # Do not reflect payloads, tokens, SQL, connection strings or traces.
            return error_response(request.scope, 500, 'internal_error')

    def route(path, action, method):
        # Distinct callable per route; no caller-controlled action dispatch.
        async def handle(request):
            return await endpoint(request)
        handle.action = action
        return Route(path, handle, methods=[method])

    async def http_error(request, exc):
        code = 'not_found' if exc.status_code == 404 else 'method_not_allowed' if exc.status_code == 405 else 'invalid_request'
        response = error_response(request.scope, exc.status_code, code)
        if exc.status_code == 405:
            response.headers['Allow'] = exc.headers.get('Allow', '') if exc.headers else ''
        return response

    base = '/v1/workspaces/{tenant}'
    routes = [
        route(base + '/context', 'workspace_context', 'GET'),
        route(base + '/organisations', 'list_organisations', 'GET'),
        route(base + '/organisations', 'create_organisation', 'POST'),
        route(base + '/organisations/{object_id}/notes', 'list_notes', 'GET'),
        route(base + '/organisations/{object_id}', 'get_organisation', 'GET'),
        route(base + '/organisations/{object_id}/notes', 'create_note', 'POST'),
        route(base + '/notes/{object_id}', 'get_note', 'GET'),
    ]
    if directory_connection_factory is not None:
        if not callable(directory_connection_factory):
            raise ValueError('Server-owned directory connection factory required')
        routes.append(route('/v1/workspaces','list_workspaces','GET'))
    if evidence_quarantine_dir is not None:
        from .customer_evidence import CustomerEvidence
        routes.extend(CustomerEvidence(verifier, connection_factory, evidence_quarantine_dir,
                                       status_connections=scan_status_connection_factory,
                                       request_connections=scan_request_connection_factory).routes())
    app = Starlette(debug=False,routes=routes,exception_handlers={HTTPException:http_error})
    return Boundary(app, allowed_hosts)
