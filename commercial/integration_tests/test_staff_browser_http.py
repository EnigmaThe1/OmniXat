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
