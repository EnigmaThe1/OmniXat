from contextlib import nullcontext
from secrets import token_urlsafe
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from urllib.parse import urlencode

from starlette.testclient import TestClient

from omnixat_core.staff_browser import create_staff_browser_app


class StaffBrowserBoundaryTests(TestCase):
    origin = "https://staff.example.invalid"
    callback = "/staff/login/callback"

    def setUp(self):
        self.provider = Mock()
        self.provider.redirect_uri = self.origin + self.callback
        self.provider.begin.return_value = "https://provider.example.invalid/realms/fictional/auth"
        self.admit = Mock(return_value=True)
        self.open_db = Mock(side_effect=lambda: nullcontext(object()))
        self.app = create_staff_browser_app(origin=self.origin, provider=self.provider,
                                            attempts=self.open_db, sessions=self.open_db,
                                            directory=self.open_db, admit=self.admit)
        self.client = self.enterContext(TestClient(self.app, base_url=self.origin, follow_redirects=False))

    def test_cross_origin_posts_and_wrong_host_do_not_enter_authentication(self):
        for path in ("/staff/login", "/staff/logout"):
            for headers in ([], [("origin", "null")], [("origin", "https://other.example.invalid")],
                            [("origin", self.origin), ("origin", self.origin)]):
                with self.subTest(path=path, headers=headers):
                    self.assertEqual(self.client.post(path, headers=headers).status_code, 403)
        response = self.client.post("/staff/login", headers={"origin": self.origin, "host": "other.example.invalid"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post("http://staff.example.invalid/staff/login", headers={"origin": self.origin})
        self.assertEqual(response.status_code, 400)
        self.admit.assert_not_called()
        self.open_db.assert_not_called()

    def test_admission_failure_stops_before_opening_database(self):
        self.admit.return_value = False
        self.assertEqual(self.client.post("/staff/login", headers={"origin": self.origin}).status_code, 429)
        self.admit.side_effect = RuntimeError("fictional private diagnostic")
        response = self.client.post("/staff/login", headers={"origin": self.origin})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private diagnostic", response.text)
        self.open_db.assert_not_called()

    def test_rejects_ambiguous_callback_and_binding_without_using_provider(self):
        self.client.post("/staff/login", headers={"origin": self.origin})
        good = urlencode({"state": token_urlsafe(32), "code": "fictional-code",
                          "iss": "https://provider.example.invalid/realms/fictional"})
        for query in (good + "&state=" + token_urlsafe(32), good + "&%63ode=second",
                      good + "&unknown=1", good + "&session_state=%xx", "code=" + "x" * 8192):
            with self.subTest(length=len(query)):
                response = self.client.get(self.callback + "?" + query)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.headers["referrer-policy"], "no-referrer")
                self.assertNotIn("fictional-code", response.text)
        cookie = "__Host-omnixat-staff-binding=" + token_urlsafe(32)
        response = self.client.get(self.callback + "?" + good,
                                   headers=[("cookie", cookie), ("cookie", cookie)])
        self.assertEqual(response.status_code, 400)
        self.provider.complete.assert_not_called()

    def test_security_headers_and_no_owner_or_bearer_surface(self):
        for path in ("/admin/v1/metrics", "/v1/organisations", self.callback + "/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.headers["cache-control"], "no-store")
        response = self.client.head(self.callback)
        self.assertEqual(response.status_code, 405)
        response = self.client.get("/staff/session", headers={"authorization": "Bearer fictional"})
        self.assertEqual(response.status_code, 401)
        self.open_db.assert_not_called()

    def test_callback_configuration_must_match_exact_origin(self):
        with self.assertRaises(ValueError):
            create_staff_browser_app(origin=self.origin,
                                     provider=SimpleNamespace(redirect_uri=self.origin + "/wrong"),
                                     attempts=self.open_db, sessions=self.open_db,
                                     directory=self.open_db, admit=self.admit)

    def test_access_events_never_log_request_or_response_credentials(self):
        logger = "omnixat.staff_browser.access"
        state = token_urlsafe(32)
        self.provider.begin.return_value += "?state=" + state
        session = token_urlsafe(32)
        self.provider.complete.return_value = session
        with self.assertLogs(logger, level="INFO") as captured:
            started = self.client.post("/staff/login", headers={
                "origin": self.origin, "authorization": "Bearer fictional-request-token",
            })
            self.assertEqual(started.status_code, 303)
            binding = self.client.cookies["__Host-omnixat-staff-binding"]
            callback = self.client.get(self.callback, params={
                "state": state, "code": "fictional-secret-code",
                "iss": "https://fictional-provider.example.invalid/realms/staff",
            })
            self.assertEqual(callback.status_code, 303)
            self.assertEqual(self.client.cookies["__Host-omnixat-staff-session"], session)
            self.assertEqual(self.client.get("/fictional-secret-path?code=fictional-secret-code").status_code, 404)
        self.assertEqual([record.getMessage() for record in captured.records], [
            "staff_browser action=login status=303",
            "staff_browser action=callback status=303",
            "staff_browser action=unmatched status=404",
        ])
        for secret in (state, session, binding, "fictional-secret-code", "fictional-request-token",
                       "fictional-secret-path", "fictional-provider"):
            self.assertNotIn(secret, repr([record.__dict__ for record in captured.records]))

    def test_access_events_cover_rejection_rate_limit_and_failure_without_diagnostics(self):
        with self.assertLogs("omnixat.staff_browser.access", level="INFO") as captured:
            self.assertEqual(self.client.post("/staff/login").status_code, 403)
            self.admit.return_value = False
            self.assertEqual(self.client.get(self.callback + "?code=fictional-secret-code").status_code, 429)
            self.admit.side_effect = RuntimeError("fictional private diagnostic")
            response = self.client.get(self.callback + "?code=fictional-secret-code")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("fictional private diagnostic", response.text)
        self.assertEqual([record.args for record in captured.records],
                         [("login", 403), ("callback", 429), ("callback", 503)])
        self.assertTrue(all(record.exc_info is None for record in captured.records))
        self.open_db.assert_not_called()

    def test_access_sink_failure_does_not_turn_a_response_into_an_error(self):
        from unittest.mock import patch

        with patch("omnixat_core.staff_browser._ACCESS_LOG.info", side_effect=RuntimeError):
            response = self.client.post("/staff/login", headers={"origin": self.origin})
        self.assertEqual(response.status_code, 303)
        self.assertIn("__Host-omnixat-staff-binding", self.client.cookies)

    def test_expired_admission_never_starts_login_and_next_request_has_fresh_budget(self):
        from unittest.mock import patch

        elapsed = [0]

        def slow_admission(*args):
            elapsed[0] = 9
            return True

        with patch("omnixat_core.staff_deadline.monotonic", side_effect=lambda: elapsed[0]):
            self.admit.side_effect = slow_admission
            late = self.client.post("/staff/login", headers={"origin": self.origin})
            self.assertEqual(late.status_code, 503)
            self.assertNotIn("set-cookie", late.headers)
            self.open_db.assert_not_called()
            self.provider.begin.assert_not_called()

            self.admit.side_effect = None
            self.assertEqual(self.client.post("/staff/login", headers={"origin": self.origin}).status_code, 303)

    def test_late_connection_is_released_without_starting_provider_work(self):
        from contextlib import contextmanager
        from unittest.mock import patch

        elapsed, released = [0], []

        @contextmanager
        def slow_open():
            elapsed[0] = 9
            try:
                yield object()
            finally:
                released.append(True)

        self.open_db.side_effect = slow_open
        with patch("omnixat_core.staff_deadline.monotonic", side_effect=lambda: elapsed[0]):
            late = self.client.post("/staff/login", headers={"origin": self.origin})
        self.assertEqual(late.status_code, 503)
        self.assertNotIn("set-cookie", late.headers)
        self.assertEqual(released, [True])
        self.provider.begin.assert_not_called()

    def test_late_callback_response_never_sets_session_cookie(self):
        from unittest.mock import patch

        elapsed = [0]

        def slow_complete(*args, **kwargs):
            elapsed[0] = 9
            return token_urlsafe(32)

        self.provider.complete.side_effect = slow_complete
        with patch("omnixat_core.staff_deadline.monotonic", side_effect=lambda: elapsed[0]):
            self.assertEqual(self.client.post("/staff/login", headers={"origin": self.origin}).status_code, 303)
            late = self.client.get(self.callback, params={
                "state": token_urlsafe(32), "code": "fictional-secret-code",
                "iss": "https://fictional.example.invalid/realms/staff",
            })
        self.assertEqual(late.status_code, 503)
        self.assertNotIn("set-cookie", late.headers)
        self.assertNotIn("location", late.headers)
        self.assertNotIn("__Host-omnixat-staff-session", self.client.cookies)
