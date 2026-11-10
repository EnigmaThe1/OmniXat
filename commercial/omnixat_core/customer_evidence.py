"""Opt-in raw evidence intake. No originals are served or released to a model."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryFile
from threading import BoundedSemaphore
from uuid import UUID
import os
import stat

import anyio
import psycopg
from psycopg.rows import dict_row
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.requests import ClientDisconnect
from starlette.routing import Route

from .access import require_tenant
from .evidence_intake import stage_evidence, EVIDENCE_MEDIA_TYPES, MAX_EVIDENCE_BYTES
from .evidence_postgres import register_evidence, EvidenceConflict
from .evidence_quarantine_postgres import store_quarantined_evidence
from .identity import AuthenticationError
from .identity_postgres import resolve_record_principal
from .postgres import _tenant_transaction
from .http_api import ApiError, error_response


UPLOAD_TIMEOUT_SECONDS = 15


def private_spool(path):
    directory = Path(path)
    metadata = directory.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077):
        raise ValueError('Evidence spool requires a private service-owned directory')
    return directory


def evidence_actor(connection, verifier, token, tenant, *, write=False):
    # Record admission stays records-only. Evidence scopes cannot grant billing,
    # approval, membership administration or authority to a different actor kind.
    actor = resolve_record_principal(connection, verifier, token, tenant, write=write)
    identity = verifier.verify(token)
    actor = replace(actor, api_scopes=identity.scopes & {'evidence:read', 'evidence:register'})
    require_tenant(actor, tenant, 'evidence:read')
    if write:
        require_tenant(actor, tenant, 'evidence:register')
    return actor


class CustomerEvidence:
    def __init__(self, verifier, connection_factory, quarantine_dir):
        self.verifier, self.connections = verifier, connection_factory
        self.directory = private_spool(quarantine_dir)
        self.admission = BoundedSemaphore(4)

    def authorize(self, token, tenant, organisation, *, write=False):
        with self.connections() as connection:
            actor = evidence_actor(connection, self.verifier, token, tenant, write=write)
            with _tenant_transaction(connection, UUID(tenant), tables_required=('organisations',)):
                if connection.execute('SELECT 1 FROM omnixat.organisations WHERE tenant_id=%s AND id=%s',
                                      (tenant, organisation)).fetchone() is None:
                    raise KeyError('Organisation not found')
            return actor

    def listing(self, token, tenant, organisation, after, limit):
        self.authorize(token, tenant, organisation)
        with self.connections() as connection:
            # Do not cache the authority resolved for the preceding call.
            evidence_actor(connection, self.verifier, token, tenant)
            with _tenant_transaction(connection, UUID(tenant), tables_required=(
                    'evidence_registrations', 'evidence_quarantine')):
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute('''SELECT e.id,e.media_type,e.byte_size,e.registered_at,q.stored_at
                        FROM omnixat.evidence_registrations e LEFT JOIN omnixat.evidence_quarantine q
                          ON q.tenant_id=e.tenant_id AND q.evidence_id=e.id
                        WHERE e.tenant_id=%s AND e.organisation_id=%s
                          AND (%s::uuid IS NULL OR e.id > %s) ORDER BY e.id LIMIT %s''',
                        (tenant, organisation, after, after, limit+1))
                    rows = cursor.fetchall()
        items = [{key: str(value) if isinstance(value, UUID) or hasattr(value, 'isoformat') else value
                  for key,value in row.items()} for row in rows[:limit]]
        return {'items':items, 'next_cursor':items[-1]['id'] if len(rows)>limit else None}

    def receipt(self, token, tenant, organisation, evidence):
        self.authorize(token, tenant, organisation)
        with self.connections() as connection:
            evidence_actor(connection, self.verifier, token, tenant)
            with _tenant_transaction(connection, UUID(tenant), tables_required=(
                    'evidence_registrations', 'evidence_quarantine')):
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute('''SELECT e.id,e.organisation_id,e.media_type,e.byte_size,
                            encode(e.content_sha256,'hex') AS content_sha256,e.registered_at,q.stored_at
                        FROM omnixat.evidence_registrations e LEFT JOIN omnixat.evidence_quarantine q
                          ON q.tenant_id=e.tenant_id AND q.evidence_id=e.id
                        WHERE e.tenant_id=%s AND e.organisation_id=%s AND e.id=%s''',
                        (tenant, organisation, evidence))
                    row = cursor.fetchone()
        if row is None:
            raise KeyError('Evidence not found')
        return {key: value.isoformat() if hasattr(value, 'isoformat') else
                str(value) if isinstance(value, UUID) else value for key, value in row.items()}

    def persist(self, token, tenant, organisation, source, media_type, size):
        source.seek(0)
        with stage_evidence(source, media_type=media_type, quarantine_dir=self.directory,
                            expected_size=size) as staged:
            with self.connections() as connection:
                actor = evidence_actor(connection, self.verifier, token, tenant, write=True)
                registration = register_evidence(connection, actor, tenant, organisation,
                    content_sha256=staged.content_sha256, media_type=media_type, byte_size=staged.byte_size)
                # Registry and payload have separate transactions. A retry can finish
                # an interrupted registration, and must recheck current authority.
                actor = evidence_actor(connection, self.verifier, token, tenant, write=True)
                receipt = store_quarantined_evidence(connection, actor, tenant, organisation, registration.id, staged)
        return {'id':str(receipt.evidence_id), 'stored_at':receipt.stored_at.isoformat(),
                'registered_at':registration.registered_at.isoformat(), 'media_type':media_type, 'byte_size':size}

    async def endpoint(self, request):
        try:
            headers = request.headers.getlist('authorization')
            parts = headers[0].split(' ') if len(headers)==1 and len(headers[0])<=16400 else []
            if len(parts)!=2 or parts[0].lower()!='bearer' or not parts[1]:
                raise ApiError(401, 'authentication_required')
            token = parts[1]
            try:
                self.verifier.verify(token)
            except AuthenticationError:
                raise ApiError(401, 'invalid_token') from None
            try:
                tenant = str(UUID(request.path_params['tenant']))
                organisation = str(UUID(request.path_params['object_id']))
                evidence = str(UUID(request.path_params['evidence_id'])) if 'evidence_id' in request.path_params else None
            except ValueError:
                raise ApiError(400, 'invalid_identifier') from None
            if request.headers.getlist('idempotency-key'):
                raise ApiError(400, 'unsupported_parameter')
            if request.method in ('GET', 'HEAD'):
                if evidence is not None:
                    if request.query_params:
                        raise ApiError(400, 'unsupported_parameter')
                    result = await run_in_threadpool(self.receipt, token, tenant, organisation, evidence)
                    return JSONResponse({'data':result,'request_id':request.scope['request_id']})
                pairs = list(request.query_params.multi_items())
                if any(k not in ('after','limit') for k,v in pairs) or len(dict(pairs))!=len(pairs):
                    raise ApiError(400, 'unsupported_parameter')
                try:
                    raw = request.query_params.get('limit','50')
                    limit = int(raw)
                    if raw != str(limit) or not 1 <= limit <= 50:
                        raise ValueError()
                    after = request.query_params.get('after')
                    if after is not None and str(UUID(after))!=after:
                        raise ValueError()
                except ValueError:
                    raise ApiError(400, 'invalid_page') from None
                result = await run_in_threadpool(self.listing, token, tenant, organisation, after, limit)
                return JSONResponse({'data':result,'request_id':request.scope['request_id']})
            if request.query_params:
                raise ApiError(400, 'unsupported_parameter')
            media_types = request.headers.getlist('content-type')
            encodings = request.headers.getlist('content-encoding')
            if len(media_types)!=1 or media_types[0] not in EVIDENCE_MEDIA_TYPES or encodings not in ([], ['identity']):
                raise ApiError(415, 'unsupported_media_type')
            lengths = request.headers.getlist('content-length')
            if lengths and (len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0])>10):
                raise ApiError(400, 'invalid_request')
            expected = int(lengths[0]) if lengths else None
            if expected is not None and not 1 <= expected <= MAX_EVIDENCE_BYTES:
                raise ApiError(413, 'body_too_large')
            await run_in_threadpool(self.authorize, token, tenant, organisation, write=True)
            if not self.admission.acquire(blocking=False):
                raise ApiError(503, 'service_unavailable')
            try:
                private_spool(self.directory)
                with TemporaryFile(mode='w+b', dir=self.directory) as source:
                    size = 0
                    try:
                        with anyio.fail_after(UPLOAD_TIMEOUT_SECONDS):
                            async for chunk in request.stream():
                                size += len(chunk)
                                if size > MAX_EVIDENCE_BYTES or expected is not None and size > expected:
                                    raise ApiError(413, 'body_too_large')
                                if await run_in_threadpool(source.write, chunk) != len(chunk):
                                    raise OSError('Incomplete spool write')
                    except TimeoutError:
                        raise ApiError(408, 'request_timeout') from None
                    if not size or expected is not None and size != expected:
                        raise ApiError(400, 'incomplete_upload')
                    result = await run_in_threadpool(self.persist, token, tenant, organisation, source, media_types[0], size)
            finally:
                self.admission.release()
            return JSONResponse({'data':result,'request_id':request.scope['request_id']},status_code=201)
        except ApiError as error:
            return error_response(request.scope,error.status,error.code)
        except ClientDisconnect:
            return error_response(request.scope,400,'incomplete_upload')
        except PermissionError:
            # A valid token at admission may expire while the body is received
            # or between persistence units. Keep membership denial distinct from
            # token expiry so the browser retains its exact-file retry state.
            try:
                self.verifier.verify(token)
            except AuthenticationError:
                return error_response(request.scope,401,'invalid_token')
            return error_response(request.scope,403,'access_denied')
        except KeyError:
            return error_response(request.scope,404,'not_found')
        except EvidenceConflict:
            return error_response(request.scope,409,'evidence_conflict')
        except TimeoutError:
            return error_response(request.scope,503,'service_unavailable')
        except (psycopg.OperationalError, OSError):
            return error_response(request.scope,503,'service_unavailable')
        except Exception:
            return error_response(request.scope,500,'internal_error')

    def routes(self):
        return [Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence',
                      self.endpoint,methods=['GET','POST']),
                Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}',
                      self.endpoint,methods=['GET'])]
