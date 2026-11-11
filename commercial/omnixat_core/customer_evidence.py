"""Opt-in raw evidence intake. No originals are served or released to a model."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryFile
from threading import BoundedSemaphore
from uuid import UUID
import os
import json
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
from .http_api import ApiError, error_response, expected_actor, _pairs, _reject_constant


UPLOAD_TIMEOUT_SECONDS = 15


def private_spool(path):
    directory = Path(path)
    metadata = directory.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077):
        raise ValueError('Evidence spool requires a private service-owned directory')
    return directory


def evidence_actor(connection, verifier, token, tenant, *, write=False, expected_actor=None):
    # Record admission stays records-only. Evidence scopes cannot grant billing,
    # approval, membership administration or authority to a different actor kind.
    actor = resolve_record_principal(connection, verifier, token, tenant, write=write)
    if expected_actor is not None and actor.user_id != expected_actor:
        raise ApiError(409, 'session_changed')
    identity = verifier.verify(token)
    actor = replace(actor, api_scopes=identity.scopes & {'evidence:read', 'evidence:register'})
    require_tenant(actor, tenant, 'evidence:read')
    if write:
        require_tenant(actor, tenant, 'evidence:register')
    return actor


class CustomerEvidence:
    def __init__(self, verifier, connection_factory, quarantine_dir, *, status_connections=None, request_connections=None, review_connections=None, answer_connections=None, csv_request_connections=None, csv_request_status_connections=None, expense_draft_connections=None, expense_preparation_connections=None, expense_funding_read_connections=None, expense_funding_write_connections=None, expense_journal_read_connections=None, expense_journal_preview_connections=None, expense_journal_write_connections=None, journal_observation_connections=None):
        self.verifier, self.connections = verifier, connection_factory
        if status_connections is not None and not callable(status_connections):
            raise ValueError('Server-owned status connection factory required')
        self.status_connections = status_connections
        if request_connections is not None and not callable(request_connections):
            raise ValueError('Server-owned request connection factory required')
        self.request_connections = request_connections
        if review_connections is not None and not callable(review_connections):
            raise ValueError('Server-owned review connection factory required')
        self.review_connections = review_connections
        if answer_connections is not None and not callable(answer_connections):
            raise ValueError('Server-owned answer connection factory required')
        self.answer_connections = answer_connections
        if csv_request_connections is not None and not callable(csv_request_connections):
            raise ValueError('Server-owned CSV request connection factory required')
        self.csv_request_connections = csv_request_connections
        if csv_request_status_connections is not None and not callable(csv_request_status_connections):
            raise ValueError('Server-owned request-status connection factory required')
        self.csv_request_status_connections = csv_request_status_connections
        if expense_draft_connections is not None and not callable(expense_draft_connections):
            raise ValueError('Server-owned draft reader connection factory required')
        self.expense_draft_connections = expense_draft_connections
        if expense_preparation_connections is not None and not callable(expense_preparation_connections):
            raise ValueError('Server-owned preparation connection factory required')
        self.expense_preparation_connections = expense_preparation_connections
        for factory in (expense_funding_read_connections,expense_funding_write_connections):
            if factory is not None and not callable(factory):
                raise ValueError('Server-owned funding connection factories required')
        self.expense_funding_read_connections = expense_funding_read_connections
        self.expense_funding_write_connections = expense_funding_write_connections
        self.journal_connections = {'inspect':expense_journal_read_connections,
            'preview':expense_journal_preview_connections,'create':expense_journal_write_connections}
        if any(factory is not None and not callable(factory) for factory in self.journal_connections.values()):
            raise ValueError('Server-owned journal connection factories required')
        if journal_observation_connections is not None and not callable(journal_observation_connections):
            raise ValueError('Server-owned observation reader required')
        self.journal_observation_connections=journal_observation_connections
        self.directory = private_spool(quarantine_dir)
        self.admission = BoundedSemaphore(4)

    def authorize(self, token, tenant, organisation, *, write=False, expected_actor=None):
        with self.connections() as connection:
            actor = evidence_actor(connection, self.verifier, token, tenant, write=write, expected_actor=expected_actor)
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

    def scan_status(self, token, tenant, organisation, evidence):
        self.authorize(token, tenant, organisation)
        from .evidence_status_postgres import read_scan_status
        with self.status_connections() as connection:
            return read_scan_status(connection,self.verifier,token,tenant,organisation,evidence)

    def csv_review(self,token,tenant,organisation,evidence):
        self.authorize(token,tenant,organisation)
        from .customer_csv_review import read_latest_csv
        with self.review_connections() as connection:
            return read_latest_csv(connection,self.verifier,token,tenant,organisation,evidence)

    def journal_observations(self,token,tenant,organisation,evidence,draft,snapshot,after):
        self.authorize(token,tenant,organisation)
        from .customer_journal_observations import read_observations, JournalSnapshotChanged
        try:
            with self.journal_observation_connections() as connection:
                return read_observations(connection,self.verifier,token,tenant,organisation,evidence,draft,
                    snapshot_sha256=snapshot,after_reviewer=after)
        except ValueError: raise ApiError(400,'invalid_observation_page') from None
        except JournalSnapshotChanged: raise ApiError(409,'journal_snapshot_changed') from None

    def journal(self,token,tenant,organisation,evidence,draft,operation='inspect',document=None,expected=None):
        self.authorize(token,tenant,organisation,expected_actor=expected)
        from .customer_expense_journals import inspect_journal, preview_journal, create_journal, JournalActorChanged, JournalConflict, JournalPreviewChanged
        functions={'inspect':inspect_journal,'preview':preview_journal,'create':create_journal}
        try:
            with self.journal_connections[operation]() as connection:
                args=() if operation=='inspect' else (document,)
                return functions[operation](connection,self.verifier,token,tenant,organisation,evidence,draft,*args,
                    **({} if operation=='inspect' else {'expected_actor':expected}))
        except ValueError: raise ApiError(422,'invalid_journal_preparation') from None
        except JournalActorChanged: raise ApiError(409,'session_changed') from None
        except JournalConflict: raise ApiError(409,'journal_conflict') from None
        except JournalPreviewChanged: raise ApiError(409,'journal_preview_changed') from None

    def expense_funding(self,token,tenant,organisation,evidence,draft):
        self.authorize(token,tenant,organisation)
        from .customer_expense_funding import read_funding
        with self.expense_funding_read_connections() as connection:
            return read_funding(connection,self.verifier,token,tenant,organisation,evidence,draft)

    def record_funding(self,token,tenant,organisation,evidence,draft,document,expected):
        self.authorize(token,tenant,organisation,expected_actor=expected)
        from .customer_expense_funding import record_funding, FundingActorChanged, FundingConflict
        try:
            with self.expense_funding_write_connections() as connection:
                return record_funding(connection,self.verifier,token,tenant,organisation,evidence,draft,document,expected_actor=expected)
        except ValueError: raise ApiError(422,'invalid_funding_selection') from None
        except FundingActorChanged: raise ApiError(409,'session_changed') from None
        except FundingConflict: raise ApiError(409,'funding_conflict') from None

    def expense_choices(self,token,tenant,organisation,evidence):
        self.authorize(token,tenant,organisation)
        from .customer_expense_preparation import expense_choices
        with self.expense_preparation_connections() as connection:
            return expense_choices(connection,self.verifier,token,tenant,organisation,evidence)

    def create_expense(self,token,tenant,organisation,evidence,document,expected):
        self.authorize(token,tenant,organisation,expected_actor=expected)
        from .customer_expense_preparation import create_expense, PreparationActorChanged, PreparationConflict
        try:
            with self.expense_preparation_connections() as connection:
                return create_expense(connection,self.verifier,token,tenant,organisation,evidence,document,expected_actor=expected)
        except ValueError: raise ApiError(422,'invalid_expense_preparation') from None
        except PreparationActorChanged: raise ApiError(409,'session_changed') from None
        except PreparationConflict: raise ApiError(409,'expense_preparation_conflict') from None

    def expense_drafts(self,token,tenant,organisation,evidence,draft=None):
        self.authorize(token,tenant,organisation)
        from .customer_expense_drafts import read_expense_drafts
        with self.expense_draft_connections() as connection:
            return read_expense_drafts(connection,self.verifier,token,tenant,organisation,evidence,draft)

    def csv_requests(self,token,tenant,organisation,evidence,job=None):
        self.authorize(token,tenant,organisation)
        from .csv_request_status import read_requests
        with self.csv_request_status_connections() as connection:
            return read_requests(connection,self.verifier,token,tenant,organisation,evidence,job)

    def cancel_csv_request(self,token,tenant,organisation,evidence,job,expected):
        self.authorize(token,tenant,organisation,expected_actor=expected)
        from .csv_requests_postgres import cancel_csv, RequestActorChanged, CancellationUnavailable
        try:
            with self.csv_request_connections() as connection:
                return cancel_csv(connection,self.verifier,token,tenant,organisation,evidence,job,expected_actor=expected)
        except RequestActorChanged:
            raise ApiError(409,'session_changed') from None
        except CancellationUnavailable:
            raise ApiError(409,'extraction_cancellation_unavailable') from None

    def reauthorise_csv_request(self,token,tenant,organisation,evidence,job,document,expected):
        self.authorize(token,tenant,organisation,expected_actor=expected)
        from .csv_requests_postgres import reauthorise_csv, RequestActorChanged, ReauthorisationUnavailable
        from .evidence_extraction_postgres import CSVExtractionConflict
        try:
            with self.csv_request_connections() as connection:
                return reauthorise_csv(connection,self.verifier,token,tenant,organisation,evidence,job,document,expected_actor=expected)
        except ValueError:
            raise ApiError(422,'invalid_reauthorisation') from None
        except RequestActorChanged:
            raise ApiError(409,'session_changed') from None
        except (ReauthorisationUnavailable,CSVExtractionConflict):
            raise ApiError(409,'extraction_reauthorisation_unavailable') from None

    def csv_request(self,token,tenant,organisation,evidence,document,expected):
        self.authorize(token,tenant,organisation,expected_actor=expected)
        from .csv_requests_postgres import request_csv, RequestActorChanged
        from .evidence_extraction_postgres import CSVExtractionConflict
        try:
            with self.csv_request_connections() as connection:
                return request_csv(connection,self.verifier,token,tenant,organisation,evidence,document,expected_actor=expected)
        except ValueError:
            raise ApiError(422,'invalid_extraction_request') from None
        except RequestActorChanged:
            raise ApiError(409,'session_changed') from None
        except CSVExtractionConflict:
            raise ApiError(409,'extraction_request_conflict') from None

    def csv_answer(self,token,tenant,organisation,evidence,document,expected):
        self.authorize(token,tenant,organisation,expected_actor=expected)
        from .customer_csv_answers import answer_csv, AnswerActorChanged
        from .evidence_review_postgres import CSVClarificationConflict
        try:
            with self.answer_connections() as connection:
                return answer_csv(connection,self.verifier,token,tenant,organisation,evidence,document,expected_actor=expected)
        except ValueError:
            raise ApiError(422,'invalid_answer') from None
        except AnswerActorChanged:
            raise ApiError(409,'session_changed') from None
        except CSVClarificationConflict:
            raise ApiError(409,'answer_conflict') from None

    def request_scan(self, token, tenant, organisation, evidence, expected, cancel=False, reauthorise_at=None):
        self.authorize(token,tenant,organisation,expected_actor=expected)
        from .evidence_requests_postgres import request_scan, ScanRequestUnavailable, ScanRequestActorChanged
        try:
            with self.request_connections() as connection:
                return request_scan(connection,self.verifier,token,tenant,organisation,evidence,expected_actor=expected,cancel=cancel,reauthorise_at=reauthorise_at)
        except ValueError:
            raise ApiError(400,'invalid_cancellation') from None
        except ScanRequestUnavailable:
            raise ApiError(409,'scan_reauthorisation_unavailable' if reauthorise_at is not None else 'scan_request_unavailable') from None
        except ScanRequestActorChanged:
            raise ApiError(409,'session_changed') from None

    def persist(self, token, tenant, organisation, source, media_type, size, expected=None):
        source.seek(0)
        with stage_evidence(source, media_type=media_type, quarantine_dir=self.directory,
                            expected_size=size) as staged:
            with self.connections() as connection:
                actor = evidence_actor(connection, self.verifier, token, tenant, write=True, expected_actor=expected)
                registration = register_evidence(connection, actor, tenant, organisation,
                    content_sha256=staged.content_sha256, media_type=media_type, byte_size=staged.byte_size)
                # Registry and payload have separate transactions. A retry can finish
                # an interrupted registration, and must recheck current authority.
                actor = evidence_actor(connection, self.verifier, token, tenant, write=True, expected_actor=expected)
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
                draft = str(UUID(request.path_params['draft_id'])) if 'draft_id' in request.path_params else None
                job = str(UUID(request.path_params['job_id'])) if 'job_id' in request.path_params else None
            except ValueError:
                raise ApiError(400, 'invalid_identifier') from None
            initiating_actor = expected_actor(request, writing=request.method == 'POST')
            reauthorise_at=None
            cancellation_headers=request.headers.getlist('x-omnixat-cancellation')
            if request.url.path.endswith('/scan-reauthorisations'):
                if len(cancellation_headers)!=1 or not cancellation_headers[0]:
                    raise ApiError(400,'invalid_cancellation')
                reauthorise_at=cancellation_headers[0]
            elif cancellation_headers:
                raise ApiError(400,'unsupported_parameter')
            if request.headers.getlist('idempotency-key'):
                raise ApiError(400, 'unsupported_parameter')
            if request.method in ('GET', 'HEAD'):
                if evidence is not None:
                    if request.url.path.endswith('/journal-observations'):
                        pairs=list(request.query_params.multi_items())
                        if any(k not in ('snapshot_sha256','after_reviewer') for k,v in pairs) or len(dict(pairs))!=len(pairs):
                            raise ApiError(400,'unsupported_parameter')
                        result=await run_in_threadpool(self.journal_observations,token,tenant,organisation,evidence,draft,
                            request.query_params.get('snapshot_sha256'),request.query_params.get('after_reviewer'))
                        return JSONResponse({'data':result,'request_id':request.scope['request_id']})
                    if request.query_params:
                        raise ApiError(400, 'unsupported_parameter')
                    operation = self.csv_review if request.url.path.endswith('/csv-review') else self.scan_status if request.url.path.endswith('/scan-status') else self.receipt
                    if request.url.path.endswith('/journal'):
                        result=await run_in_threadpool(self.journal,token,tenant,organisation,evidence,draft)
                    elif request.url.path.endswith('/funding'):
                        result=await run_in_threadpool(self.expense_funding,token,tenant,organisation,evidence,draft)
                    elif request.url.path.endswith('/expense-choices'):
                        result=await run_in_threadpool(self.expense_choices,token,tenant,organisation,evidence)
                    elif '/expense-drafts' in request.url.path:
                        result=await run_in_threadpool(self.expense_drafts,token,tenant,organisation,evidence,draft)
                    elif '/csv-requests' in request.url.path:
                        result=await run_in_threadpool(self.csv_requests,token,tenant,organisation,evidence,job)
                    else:
                        result = await run_in_threadpool(operation, token, tenant, organisation, evidence)
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
            if (request.url.path.endswith(('/csv-answers','/csv-requests','/expense-drafts','/funding','/journal','/journal-preview'))
                    or '/csv-requests/' in request.url.path and request.url.path.endswith('/reauthorisations')):
                journal=request.url.path.endswith(('/journal','/journal-preview'))
                funding=request.url.path.endswith('/funding')
                preparation=request.url.path.endswith('/expense-drafts')
                renewal=request.url.path.endswith('/reauthorisations')
                extraction=request.url.path.endswith('/csv-requests')
                body_limit=8192 if extraction else 2048
                if initiating_actor is None:
                    raise ApiError(400,'invalid_expected_actor')
                if request.headers.getlist('content-type') != ['application/json'] or request.headers.getlist('content-encoding'):
                    raise ApiError(415,'unsupported_media_type')
                lengths=request.headers.getlist('content-length')
                if lengths and (len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdigit()
                                or len(lengths[0])>10 or int(lengths[0])>body_limit):
                    raise ApiError(413,'body_too_large')
                content=bytearray()
                try:
                    with anyio.fail_after(5):
                        async for chunk in request.stream():
                            if len(content)+len(chunk)>body_limit:
                                raise ApiError(413,'body_too_large')
                            content.extend(chunk)
                    document=json.loads(content.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=_reject_constant)
                except TimeoutError:
                    raise ApiError(408,'request_timeout') from None
                except (ValueError,UnicodeDecodeError,RecursionError):
                    raise ApiError(400,'invalid_json') from None
                if journal:
                    result=await run_in_threadpool(self.journal,token,tenant,organisation,evidence,draft,
                        'preview' if request.url.path.endswith('/journal-preview') else 'create',document,initiating_actor)
                elif funding:
                    result=await run_in_threadpool(self.record_funding,token,tenant,organisation,evidence,draft,document,initiating_actor)
                elif preparation:
                    result=await run_in_threadpool(self.create_expense,token,tenant,organisation,evidence,document,initiating_actor)
                elif renewal:
                    result=await run_in_threadpool(self.reauthorise_csv_request,token,tenant,organisation,evidence,job,document,initiating_actor)
                else:
                    result=await run_in_threadpool(self.csv_request if extraction else self.csv_answer,token,tenant,organisation,evidence,document,initiating_actor)
                return JSONResponse({'data':result,'request_id':request.scope['request_id']},status_code=201 if preparation or journal and request.url.path.endswith('/journal') else 202 if extraction or renewal else 200)
            if evidence is not None:
                # This action has no customer-selectable policy, verdict or payload.
                # Read at most the fixed empty JSON document, with a bounded wait.
                if request.headers.getlist('content-type') != ['application/json'] or request.headers.getlist('content-encoding'):
                    raise ApiError(415,'unsupported_media_type')
                if request.headers.getlist('content-length') not in ([],['2']):
                    raise ApiError(400,'invalid_request')
                content=bytearray()
                try:
                    with anyio.fail_after(5):
                        async for chunk in request.stream():
                            if len(content)+len(chunk)>2:
                                raise ApiError(400,'invalid_request')
                            content.extend(chunk)
                except TimeoutError:
                    raise ApiError(408,'request_timeout') from None
                if content!=b'{}':
                    raise ApiError(400,'invalid_request')
                if '/csv-requests/' in request.url.path:
                    if initiating_actor is None: raise ApiError(400,'invalid_expected_actor')
                    result=await run_in_threadpool(self.cancel_csv_request,token,tenant,organisation,evidence,job,initiating_actor)
                else:
                    result=await run_in_threadpool(self.request_scan,token,tenant,organisation,evidence,initiating_actor,request.url.path.endswith('/scan-cancellations'),reauthorise_at)
                return JSONResponse({'data':result,'request_id':request.scope['request_id']},status_code=202)
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
            await run_in_threadpool(self.authorize, token, tenant, organisation, write=True, expected_actor=initiating_actor)
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
                    result = await run_in_threadpool(self.persist, token, tenant, organisation, source, media_types[0], size, initiating_actor)
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
        routes = [Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence',
                      self.endpoint,methods=['GET','POST']),
                Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}',
                      self.endpoint,methods=['GET'])]
        if self.status_connections is not None:
            routes.append(Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/scan-status',
                                self.endpoint,methods=['GET']))
        if self.request_connections is not None:
            routes.append(Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/scan-requests',
                                self.endpoint,methods=['POST']))
            routes.append(Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/scan-cancellations',
                                self.endpoint,methods=['POST']))
            routes.append(Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/scan-reauthorisations',
                                self.endpoint,methods=['POST']))
        if self.review_connections is not None:
            routes.append(Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/csv-review',
                                self.endpoint,methods=['GET']))
        if self.answer_connections is not None:
            routes.append(Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/csv-answers',
                                self.endpoint,methods=['POST']))
        if self.csv_request_connections is not None:
            routes.append(Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/csv-requests',
                                self.endpoint,methods=['POST']))
            routes.append(Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/csv-requests/{job_id}/cancellations',self.endpoint,methods=['POST']))
            routes.append(Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/csv-requests/{job_id}/reauthorisations',self.endpoint,methods=['POST']))
        if self.csv_request_status_connections is not None:
            routes.extend([Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/csv-requests',self.endpoint,methods=['GET']),
                Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/csv-requests/{job_id}',self.endpoint,methods=['GET'])])
        if self.expense_draft_connections is not None:
            routes.extend([Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/expense-drafts',self.endpoint,methods=['GET']),
                Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/expense-drafts/{draft_id}',self.endpoint,methods=['GET'])])
        if self.expense_preparation_connections is not None:
            routes.extend([Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/expense-choices',self.endpoint,methods=['GET']),
                Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/expense-drafts',self.endpoint,methods=['POST'])])
        if self.journal_observation_connections is not None:
            routes.append(Route('/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/expense-drafts/{draft_id}/journal-observations',self.endpoint,methods=['GET']))
        journal_path='/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/expense-drafts/{draft_id}/journal'
        for operation,method,suffix in [('inspect','GET',''),('preview','POST','-preview'),('create','POST','')]:
            if self.journal_connections[operation] is not None:
                routes.append(Route(journal_path+suffix,self.endpoint,methods=[method]))
        funding_path='/v1/workspaces/{tenant}/organisations/{object_id}/evidence/{evidence_id}/expense-drafts/{draft_id}/funding'
        if self.expense_funding_read_connections is not None:
            routes.append(Route(funding_path,self.endpoint,methods=['GET']))
        if self.expense_funding_write_connections is not None:
            routes.append(Route(funding_path,self.endpoint,methods=['POST']))
        return routes
