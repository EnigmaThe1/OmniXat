"""Opt-in staff login qualification app. No owner routes or public listener."""
import re
from secrets import token_urlsafe
from urllib.parse import parse_qsl, urlsplit

from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .identity import AuthenticationError
from .staff_identity import STAFF_MFA_MAX_AGE_SECONDS
from .staff_sessions_postgres import resolve_staff_session, revoke_staff_session

_BINDING = "__Host-omnixat-staff-binding"
_SESSION = "__Host-omnixat-staff-session"
_CALLBACK = "/staff/login/callback"
_SESSION_PATH = "/staff/session"
_SECURITY_HEADERS = {
    b"cache-control": b"no-store",
    b"referrer-policy": b"no-referrer",
    b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'",
    b"x-content-type-options": b"nosniff",
}


def _opaque(value):
    return re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is not None


def _cookie(request, name):
    fields = request.headers.getlist("cookie")
    if sum(map(len, fields)) > 8192:
        raise AuthenticationError("Invalid cookie")
    values = []
    for field in fields:
        for item in field.split(";"):
            key, separator, value = item.strip().partition("=")
            if key.strip() == name:
                if not separator or not _opaque(value):
                    raise AuthenticationError("Invalid cookie")
                values.append(value)
    if len(values) > 1:
        raise AuthenticationError("Ambiguous cookie")
    return values[0] if values else None


def _set_cookie(response, name, value, age):
    response.set_cookie(name, value, max_age=age, path="/", secure=True, httponly=True, samesite="lax")


def _callback_query(raw):
    if not 1 <= len(raw) <= 8192 or re.search(rb"%(?![a-fA-F0-9]{2})", raw):
        raise AuthenticationError("Invalid callback")
    try:
        pairs = parse_qsl(raw.decode("ascii"), keep_blank_values=True, strict_parsing=True,
                          max_num_fields=4, errors="strict")
    except ValueError:
        raise AuthenticationError("Invalid callback") from None
    params = dict(pairs)
    required = {"state", "code", "iss"}
    if (len(params) != len(pairs) or not required <= params.keys()
            or not params.keys() <= required | {"session_state"} or not all(params.values())
            or not _opaque(params["state"])):
        raise AuthenticationError("Invalid callback")
    return params


def _error(status):
    return JSONResponse({"error": "staff authentication unavailable" if status >= 500
                         else "staff authentication request rejected"}, status_code=status)


def create_staff_browser_app(*, origin, provider, attempts, sessions, directory, admit):
    """Connection factories return context managers; admit(request, action) must fail closed."""
    parsed = urlsplit(origin)
    if (not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?", origin)
            or not parsed.hostname or parsed.netloc != parsed.netloc.lower()
            or parsed.port == 0 or parsed.port == 443
            or provider.redirect_uri != origin + _CALLBACK or not callable(admit)):
        raise ValueError("Exact staff HTTPS origin, callback and admission control required")

    def login(request):
        binding = token_urlsafe(32)
        with attempts() as connection:
            location = provider.begin(connection, browser_binding=binding)
        response = RedirectResponse(location, status_code=303)
        _set_cookie(response, _BINDING, binding, 300)
        return response

    def callback(request):
        args = _callback_query(request.scope["query_string"])
        binding = _cookie(request, _BINDING)
        if binding is None:
            return _error(400)
        with attempts() as attempt_db, sessions() as session_db, directory() as directory_db:
            token = provider.complete(attempt_db, session_db, directory_db, state=args["state"],
                                      browser_binding=binding, response_issuer=args["iss"], code=args["code"])
        response = RedirectResponse(_SESSION_PATH, status_code=303)
        _set_cookie(response, _BINDING, "", 0)
        _set_cookie(response, _SESSION, token, STAFF_MFA_MAX_AGE_SECONDS)
        return response

    def status(request):
        token = _cookie(request, _SESSION)
        if token is None:
            return _error(401)
        with sessions() as session_db, directory() as directory_db:
            resolve_staff_session(session_db, directory_db, token)
        return JSONResponse({"signed_in": True})

    def logout(request):
        token = _cookie(request, _SESSION)
        if token is not None:
            with sessions() as connection:
                revoke_staff_session(connection, token)
        response = Response(status_code=204)
        _set_cookie(response, _BINDING, "", 0)
        _set_cookie(response, _SESSION, "", 0)
        return response

    def route(path, method, action, handler):
        def endpoint(request):
            if request.method != method:
                return _error(405)
            if method == "POST" and request.headers.getlist("origin") != [origin]:
                return _error(403)
            try:
                if admit(request, action) is not True:
                    return _error(429)
                return handler(request)
            except AuthenticationError:
                return _error(401 if action == "session" else 400)
            except Exception:
                # Never reflect upstream/DB diagnostics or let the ASGI server
                # print a traceback that may include callback credentials.
                return _error(503)
        return Route(path, endpoint, methods=[method])

    app = Starlette(debug=False, routes=[
        route("/staff/login", "POST", "login", login),
        route(_CALLBACK, "GET", "callback", callback),
        route(_SESSION_PATH, "GET", "session", status),
        route("/staff/logout", "POST", "logout", logout),
    ])

    app.router.redirect_slashes = False

    async def secure_app(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = [(key, val) for key, val in message.get("headers", []) if key not in _SECURITY_HEADERS]
                message = {**message, "headers": headers + list(_SECURITY_HEADERS.items())}
            await send(message)

        hosts = [value for name, value in scope["headers"] if name.lower() == b"host"]
        if scope["scheme"] != "https" or hosts != [parsed.netloc.encode("ascii")]:
            await _error(400)(scope, receive, secure_send)
            return
        await app(scope, receive, secure_send)

    return secure_app
