import os
import tempfile
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException, Request

from app import db, dingtalk_auth, main


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def make_request(path: str, cookie: str = "", referer: str = "") -> Request:
    headers = [(b"host", b"testserver")]
    if cookie:
        headers.append((b"cookie", cookie.encode("ascii")))
    if referer:
        headers.append((b"referer", referer.encode("ascii")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": headers,
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
            "app": main.app,
            "router": main.app.router,
        }
    )


def response_cookie(response, name: str) -> str:
    for key, value in response.raw_headers:
        if key.lower() != b"set-cookie":
            continue
        cookies = SimpleCookie()
        cookies.load(value.decode("latin-1"))
        if name in cookies:
            return cookies[name].value
    return ""


class DingTalkAuthTest(unittest.TestCase):
    def test_work_notification_targets_deduplicated_organization_users(self):
        responses = iter(
            [
                FakeResponse({"accessToken": "app-token", "expireIn": 7200}),
                FakeResponse({"errcode": 0, "task_id": 321}),
            ]
        )
        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            return next(responses)

        with patch.object(dingtalk_auth.requests, "post", side_effect=fake_post):
            result = dingtalk_auth.send_work_notification(
                ["staff-7", " staff-7 "],
                "hello",
                client_id="ding-client",
                client_secret="ding-secret",
                agent_id="1234567890",
            )

        self.assertEqual(result, {"task_id": "321", "recipient_count": 1})
        self.assertEqual(calls[0][0], dingtalk_auth.APP_TOKEN_URL)
        self.assertEqual(calls[1][0], dingtalk_auth.WORK_NOTIFICATION_URL)
        self.assertEqual(calls[1][1]["params"], {"access_token": "app-token"})
        self.assertEqual(
            calls[1][1]["json"],
            {
                "agent_id": 1234567890,
                "userid_list": "staff-7",
                "msg": {"msgtype": "text", "text": {"content": "hello"}},
            },
        )

    def test_work_notification_rejects_missing_recipients_content_and_agent(self):
        with self.assertRaisesRegex(ValueError, "recipient"):
            dingtalk_auth.send_work_notification([], "hello", "id", "secret", "123")
        with self.assertRaisesRegex(ValueError, "content"):
            dingtalk_auth.send_work_notification(["staff-7"], " ", "id", "secret", "123")
        with self.assertRaisesRegex(ValueError, "agent"):
            dingtalk_auth.send_work_notification(["staff-7"], "hello", "id", "secret", "not-a-number")

    def test_authorization_url_uses_current_oauth_endpoint_and_callback(self):
        url = dingtalk_auth.authorization_url(
            client_id="ding-client",
            redirect_uri="https://assets.example.com/auth/dingtalk/callback",
            state="signed-state",
        )
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "login.dingtalk.com")
        self.assertEqual(parsed.path, "/oauth2/auth")
        self.assertEqual(query["client_id"], ["ding-client"])
        self.assertEqual(query["redirect_uri"], ["https://assets.example.com/auth/dingtalk/callback"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["scope"], ["openid"])
        self.assertEqual(query["state"], ["signed-state"])

    def test_local_frontend_referer_supplies_callback_port_when_env_is_absent(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DINGTALK_REDIRECT_URI", None)
            request = make_request(
                "/auth/dingtalk/start",
                referer="http://127.0.0.1:4173/",
            )
            self.assertEqual(
                main.dingtalk_redirect_uri(request),
                "http://127.0.0.1:4173/auth/dingtalk/callback",
            )

    def test_production_api_callback_is_supported_exactly_as_registered(self):
        callback = "https://pr.kairaygolf.com/api/auth/dingtalk/callback"
        with patch.dict(os.environ, {"DINGTALK_REDIRECT_URI": callback}):
            self.assertEqual(
                main.dingtalk_redirect_uri(make_request("/auth/dingtalk/start")),
                callback,
            )
        callback_paths = {
            route.path
            for route in main.app.routes
            if getattr(route, "name", "") == "dingtalk_callback"
        }
        self.assertIn("/api/auth/dingtalk/callback", callback_paths)
        self.assertIn("/auth/dingtalk/callback", callback_paths)
        start_paths = {
            route.path
            for route in main.app.routes
            if getattr(route, "name", "") == "dingtalk_start"
        }
        self.assertIn("/api/auth/dingtalk/start", start_paths)
        self.assertIn("/auth/dingtalk/start", start_paths)

        with patch.dict(
            os.environ,
            {
                "DINGTALK_CLIENT_ID": "ding-client",
                "DINGTALK_CLIENT_SECRET": "ding-secret",
                "DINGTALK_REDIRECT_URI": callback,
            },
        ):
            response = main.dingtalk_start(make_request("/api/auth/dingtalk/start"))
        state_cookie_headers = [
            value.decode("latin-1")
            for key, value in response.raw_headers
            if key.lower() == b"set-cookie" and "dingtalk_oauth_state=" in value.decode("latin-1")
        ]
        self.assertTrue(any("Path=/;" in value for value in state_cookie_headers))

    def test_dingtalk_identity_is_idempotent_and_never_grants_admin(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            profile = {
                "unionId": "union-123",
                "openId": "open-123",
                "nick": "Ding User",
                "email": "ding.user@example.com",
            }

            first = db.find_or_create_dingtalk_user(conn, profile)
            second = db.find_or_create_dingtalk_user(conn, profile)

            self.assertEqual(first["id"], second["id"])
            self.assertEqual(first["role"], "internal_staff")
            self.assertEqual(first["email"], "ding.user@example.com")
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM user_identities WHERE provider='dingtalk'").fetchone()[0],
                1,
            )
            conn.close()

    def test_verified_information_technology_department_grants_and_revokes_super_admin(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            profile = {
                "unionId": "union-it-admin",
                "openId": "open-it-admin",
                "nick": "IT Admin",
                "email": "it.admin@example.com",
            }

            promoted = db.find_or_create_dingtalk_user(
                conn,
                profile,
                department_names=["信息技术部"],
                departments_verified=True,
            )
            self.assertEqual(promoted["role"], "super_admin")
            identity = conn.execute(
                "SELECT * FROM user_identities WHERE provider_subject='union-it-admin'"
            ).fetchone()
            self.assertEqual(identity["department_role_granted"], 1)
            self.assertEqual(identity["role_before_department_grant"], "internal_staff")

            revoked = db.find_or_create_dingtalk_user(
                conn,
                profile,
                department_names=["销售部"],
                departments_verified=True,
            )
            self.assertEqual(revoked["role"], "internal_staff")

            unverified = db.find_or_create_dingtalk_user(
                conn,
                {**profile, "unionId": "union-unverified", "email": "unverified@example.com"},
                department_names=["信息技术部"],
                departments_verified=False,
            )
            self.assertEqual(unverified["role"], "internal_staff")
            conn.close()

    def test_department_lookup_uses_server_side_dingtalk_directory(self):
        responses = iter(
            [
                FakeResponse({"accessToken": "app-token", "expireIn": 7200}),
                FakeResponse({"errcode": 0, "result": {"userid": "staff-1"}}),
                FakeResponse({"errcode": 0, "result": {"dept_id_list": [2, 9]}}),
                FakeResponse({"errcode": 0, "result": {"name": "销售部"}}),
                FakeResponse({"errcode": 0, "result": {"name": "信息技术部"}}),
            ]
        )
        urls = []

        def fake_post(url, **_kwargs):
            urls.append(url)
            return next(responses)

        with patch.object(dingtalk_auth.requests, "post", side_effect=fake_post):
            names = dingtalk_auth.get_department_names(
                {"unionId": "union-directory"},
                "ding-client",
                "ding-secret",
            )

        self.assertEqual(names, ["销售部", "信息技术部"])
        self.assertEqual(urls[0], dingtalk_auth.APP_TOKEN_URL)
        self.assertIn("topapi/user/getbyunionid", urls[1])
        self.assertIn("topapi/v2/user/get", urls[2])
        self.assertTrue(all("topapi/v2/department/get" in url for url in urls[3:]))

    def test_organization_directory_recurses_and_deduplicates_members(self):
        responses = iter(
            [
                FakeResponse({"accessToken": "app-token", "expireIn": 7200}),
                FakeResponse({"errcode": 0, "result": [{"dept_id": 2, "name": "市场部", "parent_id": 1}]}),
                FakeResponse({"errcode": 0, "result": {"list": [], "has_more": False}}),
                FakeResponse({"errcode": 0, "result": []}),
                FakeResponse({"errcode": 0, "result": {"list": [{"userid": "staff-7", "name": "陈晓"}], "has_more": False}}),
            ]
        )
        with patch.object(dingtalk_auth.requests, "post", side_effect=lambda *_args, **_kwargs: next(responses)):
            directory = dingtalk_auth.get_organization_directory("ding-client", "ding-secret")

        self.assertEqual([item["name"] for item in directory["departments"]], ["全部组织", "市场部"])
        self.assertEqual(
            directory["members"],
            [{"user_id": "staff-7", "name": "陈晓", "department_ids": ["2"]}],
        )

    def test_super_admin_can_grant_and_revoke_admin_by_dingtalk_user_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            grantor = conn.execute("SELECT id FROM users WHERE role='super_admin'").fetchone()
            db.set_dingtalk_admin_grant(
                conn,
                provider_user_id="staff-7",
                display_name="陈晓",
                department_names=["市场部"],
                granted_by_user_id=int(grantor["id"]),
                enabled=True,
            )
            profile = {
                "unionId": "union-staff-7",
                "openId": "open-staff-7",
                "nick": "陈晓",
                "email": "staff7@example.com",
            }
            granted = db.find_or_create_dingtalk_user(
                conn,
                profile,
                provider_user_id="staff-7",
                department_names=["市场部"],
                departments_verified=True,
            )
            self.assertEqual(granted["role"], "admin")
            self.assertTrue(db.dingtalk_member_access(conn)["staff-7"]["admin_granted"])

            db.set_dingtalk_admin_grant(
                conn,
                provider_user_id="staff-7",
                display_name="陈晓",
                department_names=["市场部"],
                granted_by_user_id=int(grantor["id"]),
                enabled=False,
            )
            revoked = conn.execute("SELECT role FROM users WHERE id=?", (granted["id"],)).fetchone()
            self.assertEqual(revoked["role"], "internal_staff")
            self.assertFalse(db.dingtalk_member_access(conn)["staff-7"]["admin_granted"])
            conn.close()

    def test_legacy_account_creation_cannot_create_privileged_roles(self):
        for role in ("admin", "super_admin"):
            with self.assertRaises(HTTPException) as denied:
                main.admin_create_user(
                    email=f"{role}@example.com",
                    name=role,
                    role=role,
                    password="password123",
                    user={"id": 1, "role": "super_admin"},
                )
            self.assertEqual(denied.exception.status_code, 403)

    def test_admin_can_create_only_customer_accounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "test.db")
            db.init_db(conn)
            original_connect = db.connect
            db.connect = lambda *_args, **_kwargs: conn
            try:
                for role in ("overseas_customer", "domestic_customer", "service_provider"):
                    main.admin_create_user(
                        email=f"{role}@example.com",
                        name=role,
                        role=role,
                        password="password123",
                        user={"role": "admin"},
                    )
                with self.assertRaises(HTTPException) as denied:
                    main.admin_create_user(
                        email="internal@example.com",
                        name="Internal",
                        role="internal_staff",
                        password="password123",
                        user={"role": "admin"},
                    )
                self.assertEqual(denied.exception.status_code, 403)
                self.assertEqual(
                    {row["role"] for row in db.list_customer_users(conn)},
                    {"overseas_customer", "domestic_customer", "service_provider"},
                )
            finally:
                db.connect = original_connect
                conn.close()

    def test_oauth_round_trip_creates_session_and_rejects_bad_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_db_path = db.DB_PATH
            db.DB_PATH = Path(tmp) / "test.db"
            conn = db.connect()
            try:
                db.init_db(conn)
            finally:
                conn.close()
            profile = {
                "unionId": "union-round-trip",
                "openId": "open-round-trip",
                "nick": "Round Trip User",
                "email": "round.trip@example.com",
            }
            try:
                with patch.dict(
                    os.environ,
                    {
                        "DINGTALK_CLIENT_ID": "ding-client",
                        "DINGTALK_CLIENT_SECRET": "ding-secret",
                    },
                    clear=False,
                ), patch.object(dingtalk_auth, "exchange_code", return_value="user-access-token") as exchange, patch.object(
                    dingtalk_auth,
                    "get_user_profile",
                    return_value=profile,
                ), patch.object(
                    dingtalk_auth,
                    "get_organization_membership",
                    return_value={"user_id": "staff-round-trip", "department_names": ["销售部"]},
                ):
                    started = main.dingtalk_start(make_request("/auth/dingtalk/start"))
                    self.assertEqual(started.status_code, 302)
                    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
                    state_cookie = response_cookie(started, "dingtalk_oauth_state")
                    self.assertTrue(state_cookie)

                    with self.assertRaises(HTTPException) as bad:
                        main.dingtalk_callback(
                            make_request("/auth/dingtalk/callback"),
                            authCode="bad-code",
                            code="",
                            state=state,
                            error="",
                        )
                    self.assertEqual(bad.exception.status_code, 400)

                    callback = main.dingtalk_callback(
                        make_request(
                            "/auth/dingtalk/callback",
                            cookie=f"dingtalk_oauth_state={state_cookie}",
                        ),
                        authCode="valid-code",
                        code="",
                        state=state,
                        error="",
                    )
                    self.assertEqual(callback.status_code, 303)
                    self.assertEqual(callback.headers["location"], "/#catalogue")
                    exchange.assert_called_once_with("valid-code", "ding-client", "ding-secret")

                    session_cookie = response_cookie(callback, "session")
                    self.assertTrue(session_cookie)
                    user = main.user_payload(
                        main.current_user(make_request("/api/session", cookie=f"session={session_cookie}"))
                    )
                    self.assertEqual(user["email"], "round.trip@example.com")
                    self.assertEqual(user["role"], "internal_staff")
                    self.assertFalse(user["is_admin"])
                    activity_conn = db.connect()
                    try:
                        activity = activity_conn.execute(
                            """
                            SELECT event_type, detail FROM user_activity_events
                            WHERE user_id=? ORDER BY id DESC LIMIT 1
                            """,
                            (user["id"],),
                        ).fetchone()
                        self.assertEqual((activity["event_type"], activity["detail"]), ("login", "dingtalk"))
                    finally:
                        activity_conn.close()
            finally:
                db.DB_PATH = old_db_path


if __name__ == "__main__":
    unittest.main()
