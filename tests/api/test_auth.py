"""로그인: 초대 가입, 로그인·로그아웃, 비밀번호 재설정, 세션 연장. DB 통합은 SHEET_FORGE_TEST_DATABASE_URL이 있을 때만 돈다."""
import os
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.api import auth_service
from app.api.errors import ApiError
from app.api.main import create_app
from app.api.settings import Settings
from app.auth.passwords import hash_password, verify_password
from app.auth.tokens import hash_token, new_token
from app.db.database import Database
from app.db.models import AuthSession
from app.storage.images import MemoryImageStore

TEST_URL = os.environ.get("SHEET_FORGE_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parent.parent.parent
PW = "correct-horse-1"


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, text):
        self.sent.append((to, subject, text))

    def token(self) -> str:
        return re.search(r"token=([\w-]+)", self.sent[-1][2]).group(1)


class UnitTest(unittest.TestCase):
    def test_password_hash(self):
        h = hash_password(PW)
        self.assertTrue(verify_password(h, PW))
        self.assertFalse(verify_password(h, "wrong-password"))
        self.assertFalse(verify_password(None, PW))          # 없는 계정도 예외 없이 False
        self.assertFalse(verify_password("not-a-hash", PW))  # 깨진 해시도 False
        self.assertNotEqual(h, hash_password(PW))            # 솔트가 달라 매번 다르다

    def test_tokens(self):
        t = new_token()
        self.assertEqual(len(t), 43)
        self.assertEqual(len(hash_token(t)), 64)
        self.assertNotEqual(t, new_token())

    def test_settings_from_env(self):
        s = Settings.from_env({"SHEET_FORGE_AUTH_REQUIRED": "1", "SHEET_FORGE_COOKIE_SECURE": "false",
                               "SHEET_FORGE_WEB_BASE_URL": "https://x.com/", "SHEET_FORGE_SESSION_TTL_DAYS": "7"})
        self.assertTrue(s.auth_required)
        self.assertFalse(s.cookie_secure)
        self.assertEqual((s.web_base_url, s.session_ttl_days), ("https://x.com", 7))
        d = Settings.from_env({})
        self.assertFalse(d.auth_required)
        self.assertTrue(d.cookie_secure)

    def test_me_requires_login_only_when_enabled(self):
        r = TestClient(create_app(Settings(auth_required=True))).get("/me")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"]["code"], "NOT_AUTHENTICATED")
        r = TestClient(create_app(Settings(default_owner_id="o1"))).get("/me")
        self.assertEqual(r.json(), {"id": "o1", "display_name": "선생님"})

    def test_routes(self):
        paths = create_app(Settings()).openapi()["paths"]
        for p in ("/auth/invite", "/auth/invite/accept", "/auth/login", "/auth/logout",
                  "/auth/password/forgot", "/auth/password/reset"):
            self.assertIn(p, paths)


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class AuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        with mock.patch.dict(os.environ, {"SHEET_FORGE_DATABASE_URL": TEST_URL}):
            command.upgrade(cfg, "head")
        cls.db = Database(TEST_URL, "", 2, 3)

    @classmethod
    def tearDownClass(cls):
        cls.db.dispose()

    def setUp(self):
        with self.db.session() as s:
            s.execute(text("TRUNCATE users, auth_sessions, email_tokens CASCADE"))
            s.commit()
        self.now = datetime(2026, 11, 18, 3, 0, tzinfo=timezone.utc)
        self.settings = Settings(database_url=TEST_URL, auth_required=True, default_owner_id="o1",
                                 web_base_url="http://web", cookie_secure=False)
        self.app = create_app(self.settings, clock=lambda: self.now, store=MemoryImageStore())
        self.mail = FakeMailer()
        self.app.state.mailer = self.mail
        self.c = TestClient(self.app)

    def invite(self, email, password=PW, client=None):
        """초대 메일을 보내고 그 링크로 가입한다. 가입한 클라이언트(쿠키 있음)와 응답을 돌려준다."""
        with self.db.session() as s:
            auth_service.send_invite(s, self.mail, self.settings, email, now=self.now)
        client = client or TestClient(self.app)
        return client, client.post("/auth/invite/accept", json={"token": self.mail.token(), "password": password})

    def test_invite_flow(self):
        with self.db.session() as s:
            auth_service.send_invite(s, self.mail, self.settings, "  Teacher@Example.com ", now=self.now)
        to, _, body = self.mail.sent[-1]
        self.assertEqual(to, "teacher@example.com")                  # 소문자로 맞춘다
        self.assertIn("http://web/signup?token=", body)
        tok = self.mail.token()
        self.assertEqual(self.c.get("/auth/invite", params={"token": tok}).json(), {"email": "teacher@example.com"})
        self.assertEqual(self.c.get("/auth/invite", params={"token": tok}).status_code, 200)   # 조회는 링크를 쓰지 않는다
        r = self.c.post("/auth/invite/accept", json={"token": tok, "password": "short"})
        self.assertEqual(r.status_code, 422)                          # 너무 짧은 비밀번호
        r = self.c.post("/auth/invite/accept", json={"token": tok, "password": PW})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"id": "o1", "display_name": "선생님", "email": "teacher@example.com"})  # 첫 가입자는 기존 데이터를 이어받는다
        self.assertIn("sid", self.c.cookies)
        self.assertEqual(self.c.get("/me").json()["email"], "teacher@example.com")
        again = self.c.post("/auth/invite/accept", json={"token": tok, "password": PW})
        self.assertEqual((again.status_code, again.json()["error"]["code"]), (400, "INVITE_INVALID"))   # 링크는 한 번만

    def test_second_user_gets_new_id(self):
        self.invite("a@example.com")
        _, r = self.invite("b@example.com")
        self.assertTrue(r.json()["id"].startswith("user_"), r.text)

    def test_invite_expires_and_duplicates_rejected(self):
        with self.db.session() as s:
            auth_service.send_invite(s, self.mail, self.settings, "a@example.com", now=self.now)
        tok = self.mail.token()
        self.now += timedelta(days=8)
        self.assertEqual(self.c.get("/auth/invite", params={"token": tok}).status_code, 400)
        self.assertEqual(self.c.post("/auth/invite/accept", json={"token": tok, "password": PW}).status_code, 400)
        self.now -= timedelta(days=8)
        self.invite("a@example.com")
        with self.db.session() as s, self.assertRaises(ApiError) as ctx:
            auth_service.send_invite(s, self.mail, self.settings, "a@example.com", now=self.now)
        self.assertEqual(ctx.exception.code, "ALREADY_REGISTERED")

    def test_resending_invite_kills_old_link(self):
        with self.db.session() as s:
            auth_service.send_invite(s, self.mail, self.settings, "a@example.com", now=self.now)
            old = self.mail.token()
            auth_service.send_invite(s, self.mail, self.settings, "a@example.com", now=self.now)
        self.assertEqual(self.c.post("/auth/invite/accept", json={"token": old, "password": PW}).status_code, 400)
        self.assertEqual(self.c.post("/auth/invite/accept", json={"token": self.mail.token(), "password": PW}).status_code, 200)

    def test_login_logout(self):
        self.invite("a@example.com")
        c = TestClient(self.app)
        self.assertEqual(c.get("/me").status_code, 401)
        bad = c.post("/auth/login", json={"email": "a@example.com", "password": "wrong-password"})
        unknown = c.post("/auth/login", json={"email": "nobody@example.com", "password": PW})
        self.assertEqual((bad.status_code, unknown.status_code), (401, 401))
        self.assertEqual(bad.json()["error"]["code"], "INVALID_CREDENTIALS")
        self.assertEqual(bad.json()["error"]["message"], unknown.json()["error"]["message"])   # 가입 여부를 알려 주지 않는다
        ok = c.post("/auth/login", json={"email": " A@Example.com ", "password": PW})
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(c.get("/me/settings").status_code, 200)       # 다른 API도 로그인 상태로 열린다
        self.assertEqual(c.post("/auth/logout").status_code, 204)
        self.assertEqual(c.get("/me").status_code, 401)
        self.assertEqual(TestClient(self.app).post("/auth/logout").status_code, 204)   # 로그인 안 해도 204

    def test_session_slides_and_expires(self):
        self.invite("a@example.com")
        c = TestClient(self.app)
        c.post("/auth/login", json={"email": "a@example.com", "password": PW})
        self.now += timedelta(days=2)
        self.assertEqual(c.get("/me").status_code, 200)
        with self.db.session() as s:
            exp = max(s.scalars(select(AuthSession.expires_at)))
        self.assertEqual(exp, self.now + timedelta(days=30))          # 쓰면 만료가 늘어난다
        self.now += timedelta(days=31)
        self.assertEqual(c.get("/me").status_code, 401)               # 쓰지 않고 지나면 만료

    def test_forgot_and_reset(self):
        client, _ = self.invite("a@example.com")
        self.mail.sent.clear()
        r = self.c.post("/auth/password/forgot", json={"email": "nobody@example.com"})
        self.assertEqual((r.status_code, self.mail.sent), (204, []))   # 없는 이메일도 204, 메일은 없다
        self.assertEqual(self.c.post("/auth/password/forgot", json={"email": "a@example.com"}).status_code, 204)
        self.assertEqual(len(self.mail.sent), 1)
        self.assertIn("http://web/reset-password?token=", self.mail.sent[0][2])
        tok = self.mail.token()
        self.assertEqual(self.c.post("/auth/password/reset", json={"token": tok, "password": "short"}).status_code, 422)
        self.assertEqual(self.c.post("/auth/password/reset", json={"token": tok, "password": "brand-new-pw-2"}).status_code, 204)
        self.assertEqual(client.get("/me").status_code, 401)           # 기존 기기는 로그아웃된다
        r = self.c.post("/auth/password/reset", json={"token": tok, "password": "another-pw-3"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "RESET_INVALID"))   # 링크는 한 번만
        self.assertEqual(self.c.post("/auth/login", json={"email": "a@example.com", "password": PW}).status_code, 401)
        self.assertEqual(self.c.post("/auth/login", json={"email": "a@example.com", "password": "brand-new-pw-2"}).status_code, 200)

    def test_reset_link_cannot_be_used_as_invite(self):
        self.invite("a@example.com")
        self.c.post("/auth/password/forgot", json={"email": "a@example.com"})
        r = self.c.post("/auth/invite/accept", json={"token": self.mail.token(), "password": PW})
        self.assertEqual(r.status_code, 400)                           # 목적이 다른 토큰은 거절


if __name__ == "__main__":
    unittest.main()
