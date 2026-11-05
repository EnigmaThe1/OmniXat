from base64 import b64encode, urlsafe_b64encode
from hashlib import sha256
import json
from secrets import token_urlsafe
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import jwt
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from omnixat_core.access import require_staff, require_tenant
from omnixat_core.identity import AuthenticationError
from omnixat_core.keycloak_staff import KeycloakStaffLogin
from omnixat_core.staff_sessions_postgres import issue_staff_session, resolve_staff_session, revoke_staff_session
from test_staff_identity_postgres import StaffDirectoryFixture


class StaffSessionsTests(StaffDirectoryFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        name, password = "staff_session_test_" + uuid4().hex, token_urlsafe(32)
        cls.session_role = sql.Identifier(name)
        cls.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}")
                          .format(cls.session_role, sql.Literal(password)))

        def cleanup():
            cls.owner.execute(sql.SQL("DROP OWNED BY {}").format(cls.session_role))
            cls.admin.execute(sql.SQL("DROP ROLE {}").format(cls.session_role))

        cls.addClassCleanup(cleanup)
        for grant in ("USAGE ON SCHEMA omnixat_staff_session",
                      "SELECT, INSERT, DELETE ON omnixat_staff_session.sessions"):
            cls.owner.execute(sql.SQL("GRANT " + grant + " TO {}").format(cls.session_role))
        cls.session_dsn = make_conninfo(cls.runtime_dsn, user=name, password=password)
        cls.sessions = psycopg.connect(cls.session_dsn, autocommit=True)
        cls.addClassCleanup(cls.sessions.close)

    def issue(self, **claims):
        token = jwt.encode(self.claims | claims, self.key, algorithm="RS256", headers={"kid": "test"})
        return issue_staff_session(self.sessions, self.directory, self.verifier, token, expected_nonce=self.nonce)

    def test_issues_after_mfa_and_resolves_after_reconnect(self):
        self.provision()
        token = self.issue()
        with psycopg.connect(self.session_dsn, autocommit=True) as connection:
            actor = resolve_staff_session(connection, self.directory, token)
        require_staff(actor, "sandbox-metrics:read")
        with self.assertRaises(PermissionError):
            require_tenant(actor, self.a, "records:read")
        row = self.sessions.execute("""
            SELECT token_digest, extract(epoch FROM expires_at)::bigint - authenticated_at AS lifetime
            FROM omnixat_staff_session.sessions WHERE membership_id=%s
        """, (self.staff_id,)).fetchone()
        self.assertEqual(row, (sha256(token.encode("ascii")).digest(), 300))

    def test_invalid_mfa_or_missing_membership_cannot_issue(self):
        with self.assertRaises(AuthenticationError):
            self.issue()
        self.provision()
        for changes in ({"acr": "0"}, {"nonce": "cd" * 32}, {"auth_time": self.now - 300}):
            with self.subTest(changes=changes), self.assertRaises(AuthenticationError):
                self.issue(**changes)
        self.assertEqual(self.owner.execute("""
            SELECT count(*) FROM omnixat_staff_session.sessions WHERE membership_id=%s
        """, (self.staff_id,)).fetchone(), (0,))

    def test_role_changes_and_membership_revocation_apply_on_next_use(self):
        self.provision()
        token = self.issue()
        self.owner.execute("UPDATE omnixat_staff.memberships SET role='support' WHERE id=%s", (self.staff_id,))
        actor = resolve_staff_session(self.sessions, self.directory, token)
        self.assertEqual(actor.staff_role, "support")
        with self.assertRaises(PermissionError):
            require_staff(actor, "sandbox-metrics:read")
        self.owner.execute("UPDATE omnixat_staff.memberships SET revoked_at=now() WHERE id=%s", (self.staff_id,))
        with self.assertRaises(AuthenticationError):
            resolve_staff_session(self.sessions, self.directory, token)

    def test_directory_authentication_cutoff_revokes_existing_session(self):
        self.provision()
        token = self.issue()
        self.owner.execute("UPDATE omnixat_staff.memberships SET auth_valid_after=%s WHERE id=%s",
                           (self.claims["auth_time"], self.staff_id))
        with self.assertRaises(AuthenticationError):
            resolve_staff_session(self.sessions, self.directory, token)
        new = self.issue(auth_time=self.now)
        self.assertEqual(resolve_staff_session(self.sessions, self.directory, new).user_id, str(self.staff_id))

    def test_expiry_and_stale_mfa_each_fail_closed(self):
        self.provision()
        old, other = self.issue(), self.issue()
        self.owner.execute("UPDATE omnixat_staff_session.sessions SET expires_at=clock_timestamp() WHERE token_digest=%s",
                           (sha256(old.encode("ascii")).digest(),))
        self.owner.execute("UPDATE omnixat_staff_session.sessions SET authenticated_at=%s WHERE token_digest=%s",
                           (self.now - 301, sha256(other.encode("ascii")).digest()))
        for token in (old, other):
            with self.assertRaises(AuthenticationError):
                resolve_staff_session(self.sessions, self.directory, token)

    def test_logout_is_durable_idempotent_and_revokes_only_one_session(self):
        self.provision()
        first, second = self.issue(), self.issue()
        revoke_staff_session(self.sessions, first)
        revoke_staff_session(self.sessions, first)
        with psycopg.connect(self.session_dsn, autocommit=True) as connection:
            with self.assertRaises(AuthenticationError):
                resolve_staff_session(connection, self.directory, first)
            self.assertEqual(resolve_staff_session(connection, self.directory, second).user_id, str(self.staff_id))

    def test_membership_replacement_does_not_inherit_session(self):
        self.provision()
        token = self.issue()
        self.owner.execute("UPDATE omnixat_staff.memberships SET subject=%s WHERE id=%s",
                           (str(uuid4()), self.staff_id))
        self.owner.execute("""INSERT INTO omnixat_staff.memberships(id,issuer,subject,role)
            VALUES (%s,%s,%s,'platform_owner')""", (uuid4(), self.issuer, self.subject))
        with self.assertRaises(AuthenticationError):
            resolve_staff_session(self.sessions, self.directory, token)

    def test_database_credentials_are_separate_and_raw_token_is_required(self):
        self.provision()
        token = self.issue()
        for db, query in (
            (self.sessions, "UPDATE omnixat_staff_session.sessions SET expires_at=now()"),
            (self.sessions, "SELECT * FROM omnixat_staff.memberships"),
            (self.sessions, "SELECT * FROM omnixat.notes"),
            (self.directory, "SELECT * FROM omnixat_staff_session.sessions"),
            (self.runtime, "SELECT * FROM omnixat_staff_session.sessions"),
        ):
            with self.subTest(query=query), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                db.execute(query)
        for db in (self.owner, self.directory):
            with self.assertRaises(PermissionError):
                resolve_staff_session(db, self.directory, token)
        for bad in (None, sha256(token.encode("ascii")).hexdigest(), token_urlsafe(32)):
            with self.assertRaises(AuthenticationError):
                resolve_staff_session(self.sessions, self.directory, bad)


    def _keycloak_attempts(self):
        name, password = "kc_attempt_test_" + uuid4().hex, token_urlsafe(32)
        role = sql.Identifier(name)
        self.admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(role, sql.Literal(password)))

        def cleanup():
            self.owner.execute(sql.SQL("DROP OWNED BY {}").format(role))
            self.admin.execute(sql.SQL("DROP ROLE {}").format(role))

        self.addCleanup(cleanup)
        for grant in ("USAGE ON SCHEMA omnixat_staff_login",
                      "SELECT, DELETE ON omnixat_staff_login.transactions",
                      "INSERT (state_key, browser_key) ON omnixat_staff_login.transactions"):
            self.owner.execute(sql.SQL("GRANT " + grant + " TO {}").format(role))
        db = psycopg.connect(make_conninfo(self.runtime_dsn, user=name, password=password), autocommit=True)
        self.addCleanup(db.close)
        return db

    def _keycloak(self, handler):
        self.issuer += "/realms/fictional"
        self.claims["iss"] = self.issuer
        self.redirect_uri = "https://app.example.invalid/staff/callback"
        self.secret = token_urlsafe(32)
        self.provision()
        return KeycloakStaffLogin(
            issuer=self.issuer, client_id="staff", redirect_uri=self.redirect_uri,
            client_secret=self.secret, login_key=uuid4().bytes + uuid4().bytes,
            public_keys={"test": self.key.public_key()}, mfa_acr="urn:example:mfa",
            transport=httpx.MockTransport(handler))

    @staticmethod
    def _token_response(body, **headers):
        return httpx.Response(200, headers={"content-type": "application/json", **headers},
                              stream=httpx.ByteStream(body))

    def test_keycloak_code_flow_links_pkce_nonce_and_session(self):
        requests = []

        def exchange(request):
            requests.append(request)
            self.assertEqual(str(request.url), self.issuer + "/protocol/openid-connect/token")
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.headers["authorization"],
                             "Basic " + b64encode(("staff:" + self.secret).encode()).decode())
            form = parse_qs(request.content.decode())
            verifier = form.pop("code_verifier")[0]
            challenge = urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
            self.assertEqual(challenge, query["code_challenge"][0])
            self.assertEqual(form, {"grant_type": ["authorization_code"], "code": ["fictional.code"],
                                    "redirect_uri": [self.redirect_uri]})
            token = jwt.encode(self.claims | {"nonce": query["nonce"][0]}, self.key,
                               algorithm="RS256", headers={"kid": "test"})
            return self._token_response(json.dumps({"id_token": token, "access_token": "unused"}).encode())

        provider, attempts, binding = self._keycloak(exchange), self._keycloak_attempts(), token_urlsafe(32)
        url = provider.begin(attempts, browser_binding=binding)
        parsed = urlsplit(url)
        self.assertEqual(url.split("?")[0], self.issuer + "/protocol/openid-connect/auth")
        query = parse_qs(parsed.query)
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["redirect_uri"], [self.redirect_uri])
        self.assertEqual(query["max_age"], ["0"])
        self.assertEqual(query["acr_values"], ["urn:example:mfa"])
        self.assertNotIn(self.secret, url)
        callback = dict(state=query["state"][0], browser_binding=binding,
                        response_issuer=self.issuer, code="fictional.code")
        for change in ({"response_issuer": "https://wrong.example.invalid"}, {"response_issuer": None},
                       {"browser_binding": token_urlsafe(32)}, {"code": "line\nbreak"}):
            with self.subTest(change=list(change)), self.assertRaises(AuthenticationError):
                provider.complete(attempts, self.sessions, self.directory, **(callback | change))
        self.assertEqual(requests, [])
        session = provider.complete(attempts, self.sessions, self.directory, **callback)
        require_staff(resolve_staff_session(self.sessions, self.directory, session), "sandbox-metrics:read")
        with self.assertRaises(AuthenticationError):
            provider.complete(attempts, self.sessions, self.directory, **callback)
        self.assertEqual(len(requests), 1)

    def test_keycloak_exchange_fails_closed_and_cannot_retry_consumed_state(self):
        responses = iter((
            httpx.Response(307, headers={"location": "https://untrusted.example.invalid/token"}),
            self._token_response(b'{"id_token":"a","id_token":"b"}'),
            self._token_response(b"x" * 65537),
            self._token_response(b'{"id_token":"a"}', **{"content-encoding": "gzip"}),
            httpx.Response(400, json={"error": "fictional upstream error"}),
            self._token_response(b'{"id_token":"not-a-signed-token"}'),
            httpx.ReadTimeout("fictional private diagnostic"),
        ))
        requests = []

        def exchange(request):
            requests.append(str(request.url))
            outcome = next(responses)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        provider, attempts, binding = self._keycloak(exchange), self._keycloak_attempts(), token_urlsafe(32)
        for index in range(7):
            with self.subTest(index=index):
                query = parse_qs(urlsplit(provider.begin(attempts, browser_binding=binding)).query)
                for _ in range(2):
                    with self.assertRaises(AuthenticationError) as rejected:
                        provider.complete(attempts, self.sessions, self.directory, state=query["state"][0],
                                          browser_binding=binding, response_issuer=self.issuer, code="fictional")
                    self.assertNotIn("private diagnostic", str(rejected.exception))
        self.assertEqual(requests, [self.issuer + "/protocol/openid-connect/token"] * 7)
        self.assertEqual(self.sessions.execute("""
            SELECT count(*) FROM omnixat_staff_session.sessions WHERE membership_id=%s
        """, (self.staff_id,)).fetchone(), (0,))

    def test_keycloak_stops_dripping_response_at_deadline(self):
        class Drip(httpx.SyncByteStream):
            def __iter__(self):
                yield b"{"
                yield b'"'
                raise AssertionError("Exchange must stop reading once its deadline passes")

        def exchange(request):
            return httpx.Response(200, headers={"content-type": "application/json"}, stream=Drip())

        provider, attempts, binding = self._keycloak(exchange), self._keycloak_attempts(), token_urlsafe(32)
        query = parse_qs(urlsplit(provider.begin(attempts, browser_binding=binding)).query)
        with patch("omnixat_core.keycloak_staff.monotonic", side_effect=[0, 1, 6]):
            with self.assertRaises(AuthenticationError):
                provider.complete(attempts, self.sessions, self.directory, state=query["state"][0],
                                  browser_binding=binding, response_issuer=self.issuer, code="fictional")
