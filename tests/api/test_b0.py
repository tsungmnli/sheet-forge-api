"""B0: ID, 낙관적 잠금, 쉬운 문장 표, DB 장애 응답(503), DB 통합(SHEET_FORGE_TEST_DATABASE_URL이 있을 때만)."""
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import String, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.api.concurrency import etag, require_if_match
from app.api.errors import ApiError
from app.api.main import create_app
from app.api.messages import GENERIC, MESSAGES, friendly
from app.api.repo import soft_delete, update_versioned
from app.api.settings import Settings
from app.db.base import CommonColumns
from app.db.database import Database, normalize_url
from app.db.ids import is_valid_id, new_id, new_ulid

TEST_URL = os.environ.get("SHEET_FORGE_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parent.parent.parent


class IdsTest(unittest.TestCase):
    def test_format_and_validity(self):
        for prefix in ("exam", "page", "seg", "prob", "ws", "preset"):
            v = new_id(prefix)
            self.assertTrue(v.startswith(prefix + "_"))
            self.assertEqual(len(v), len(prefix) + 1 + 26)
            self.assertTrue(is_valid_id(v, prefix))
            self.assertFalse(is_valid_id(v, "exam" if prefix != "exam" else "page"))

    def test_unknown_prefix_and_garbage(self):
        with self.assertRaises(ValueError):
            new_id("nope")
        self.assertFalse(is_valid_id("exam_xyz", "exam"))
        self.assertFalse(is_valid_id("", "exam"))

    def test_sorts_by_time_and_unique(self):
        a, b = new_ulid(1_000_000), new_ulid(1_000_001)
        self.assertLess(a, b)
        self.assertEqual(len({new_ulid() for _ in range(500)}), 500)


class IfMatchTest(unittest.TestCase):
    def _req(self, value):
        headers = [] if value is None else [(b"if-match", value.encode())]
        return Request({"type": "http", "headers": headers})

    def test_accepts_etag_forms(self):
        for raw in ('"7"', 'W/"7"', "7"):
            self.assertEqual(require_if_match(self._req(raw)), 7)
        self.assertEqual(etag(7), '"7"')

    def test_missing_is_428_and_garbage_is_400(self):
        for raw, status, code in ((None, 428, "VERSION_REQUIRED"), ("", 428, "VERSION_REQUIRED"),
                                  ("abc", 400, "REQUEST_INVALID"), ("*", 400, "REQUEST_INVALID")):
            with self.assertRaises(ApiError) as cm:
                require_if_match(self._req(raw))
            self.assertEqual((cm.exception.status, cm.exception.code), (status, code))


class MessagesAndErrorsTest(unittest.TestCase):
    CODES = ("NOT_FOUND VERSION_CONFLICT VERSION_REQUIRED PROBLEM_CONFIRMED PROBLEM_BUSY MATH_UNSUPPORTED EMPTY_PROBLEM "
             "SEGMENT_HAS_PROBLEM FIGURE_REF_INVALID PHOTO_UNSUPPORTED PHOTO_TOO_LARGE ORIGINAL_EXPIRED PARENT_IN_TRASH "
             "READ_LIMIT TOO_MANY_SEGMENTS DB_UNAVAILABLE PAGE_BUSY PAGE_HAS_PROBLEMS").split()

    def test_every_new_code_has_a_sentence(self):
        for code in self.CODES:
            self.assertIn(code, MESSAGES)
            self.assertTrue(MESSAGES[code].endswith((".", "?")))
        self.assertEqual(friendly("SOMETHING_ELSE"), GENERIC)

    def test_api_error_defaults(self):
        e = ApiError(412, "VERSION_CONFLICT")
        self.assertEqual(e.message, MESSAGES["VERSION_CONFLICT"])
        self.assertFalse(e.retryable)
        self.assertTrue(ApiError(503, "X").retryable)

    def test_error_body_has_retryable(self):
        app = create_app(Settings())

        @app.get("/_boom")
        def boom():
            raise ApiError(409, "PROBLEM_BUSY")

        r = TestClient(app).get("/_boom", headers={"X-Request-Id": "rid-1"})
        self.assertEqual(r.status_code, 409)
        err = r.json()["error"]
        self.assertEqual((err["code"], err["retryable"], err["request_id"]), ("PROBLEM_BUSY", False, "rid-1"))
        self.assertEqual(err["message"], MESSAGES["PROBLEM_BUSY"])


class EnvFileTest(unittest.TestCase):
    def test_loads_file_without_overriding_existing_env(self):
        import tempfile
        from app.envfile import load_env_file
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("SF_T_A=from_file\nSF_T_B=from_file\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"SF_T_B": "from_env"}):
                self.assertTrue(load_env_file(p))
                self.assertEqual(os.environ["SF_T_A"], "from_file")
                self.assertEqual(os.environ["SF_T_B"], "from_env")
            self.assertFalse(load_env_file(Path(d) / "missing.env"))


class NoDatabaseTest(unittest.TestCase):
    def test_works_without_db_and_readyz_has_no_db_check(self):
        c = TestClient(create_app(Settings()))
        r = c.get("/readyz")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("db", r.json()["checks"])

    def test_normalize_url(self):
        self.assertEqual(normalize_url("postgresql://u:p@h/d"), "postgresql+psycopg://u:p@h/d")
        self.assertEqual(normalize_url("postgres://u:p@h/d"), "postgresql+psycopg://u:p@h/d")
        self.assertEqual(normalize_url("postgresql+psycopg://u:p@h/d"), "postgresql+psycopg://u:p@h/d")

    def test_settings_from_env(self):
        s = Settings.from_env({"SHEET_FORGE_DATABASE_URL": "postgresql://a/b", "SHEET_FORGE_DB_POOL_SIZE": "3"})
        self.assertEqual((s.database_url, s.db_pool_size, s.database_url_ro, s.default_owner_id),
                         ("postgresql://a/b", 3, "", "owner_default"))


class DbDownTest(unittest.TestCase):
    """연결할 수 없는 DB(127.0.0.1:1): liveness는 유지, readiness와 DB를 쓰는 요청은 503."""

    def _app(self):
        return create_app(Settings(database_url="postgresql://u:p@127.0.0.1:1/x", db_connect_timeout_s=1))

    def test_healthz_ok_readyz_503(self):
        c = TestClient(self._app())
        self.assertEqual(c.get("/healthz").status_code, 200)
        r = c.get("/readyz")
        self.assertEqual(r.status_code, 503)
        self.assertIs(r.json()["checks"]["db"], False)

    def test_db_error_maps_to_503_retryable(self):
        app = self._app()

        @app.get("/_db")
        def use_db(request: Request):
            with request.app.state.db.session() as s:
                s.execute(text("SELECT 1"))

        r = TestClient(app).get("/_db")
        self.assertEqual(r.status_code, 503)
        err = r.json()["error"]
        self.assertEqual((err["code"], err["retryable"]), ("DB_UNAVAILABLE", True))
        self.assertEqual(err["message"], MESSAGES["DB_UNAVAILABLE"])

    def test_no_db_configured_dependency_is_503(self):
        from fastapi import Depends
        from app.api.deps import get_session
        app = create_app(Settings())

        @app.get("/_s")
        def s(session=Depends(get_session)):
            return {}

        r = TestClient(app).get("/_s")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (503, "DB_UNAVAILABLE"))


class TBase(DeclarativeBase):
    pass


class Item(CommonColumns, TBase):
    __tablename__ = "b0_items"
    name: Mapped[str] = mapped_column(String(50), default="")


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class DbIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database(TEST_URL, "", 2, 3)
        TBase.metadata.drop_all(cls.db.rw_engine)
        TBase.metadata.create_all(cls.db.rw_engine)

    @classmethod
    def tearDownClass(cls):
        TBase.metadata.drop_all(cls.db.rw_engine)
        cls.db.dispose()

    def _make(self, owner="o1", name="a"):
        with self.db.session() as s:
            item = Item(id=new_id("exam"), owner_id=owner, name=name)
            s.add(item)
            s.commit()
            return item.id

    def test_update_versioned_bumps_and_detects_stale(self):
        iid = self._make()
        with self.db.session() as s:
            self.assertEqual(update_versioned(s, Item, iid, "o1", 1, {"name": "b"}), 2)
            s.commit()
        with self.db.session() as s:
            with self.assertRaises(ApiError) as cm:
                update_versioned(s, Item, iid, "o1", 1, {"name": "c"})  # 낡은 version
            self.assertEqual((cm.exception.status, cm.exception.code), (412, "VERSION_CONFLICT"))
            self.assertEqual(s.get(Item, iid).name, "b")

    def test_other_owner_is_404(self):
        iid = self._make(owner="o1")
        with self.db.session() as s:
            with self.assertRaises(ApiError) as cm:
                update_versioned(s, Item, iid, "o2", 1, {"name": "x"})
            self.assertEqual((cm.exception.status, cm.exception.code), (404, "NOT_FOUND"))

    def test_soft_delete_hides_row_and_bumps_version(self):
        iid = self._make()
        with self.db.session() as s:
            soft_delete(s, Item, iid, "o1", deleted_with="exam_parent")
            s.commit()
        with self.db.session() as s:
            row = s.get(Item, iid)
            self.assertIsNotNone(row.deleted_at)
            self.assertEqual((row.deleted_with, row.version), ("exam_parent", 2))
            with self.assertRaises(ApiError) as cm:
                update_versioned(s, Item, iid, "o1", 2, {"name": "x"})
            self.assertEqual(cm.exception.status, 404)
            with self.assertRaises(ApiError):
                soft_delete(s, Item, iid, "o1")  # 이미 지움

    def test_ro_session_rejects_writes(self):
        with self.db.ro_session() as s:
            self.assertEqual(s.execute(text("SELECT 1")).scalar(), 1)
            with self.assertRaises(DBAPIError):
                s.execute(text("INSERT INTO b0_items (id, owner_id) VALUES ('x', 'o')"))

    def test_readyz_ok_with_real_db(self):
        r = TestClient(create_app(Settings(database_url=TEST_URL))).get("/readyz")
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.json()["checks"]["db"], True)

    def test_migrations_upgrade_head(self):
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        with mock.patch.dict(os.environ, {"SHEET_FORGE_DATABASE_URL": TEST_URL}):
            command.upgrade(cfg, "head")
            command.upgrade(cfg, "head")  # 다시 해도 안전
        with self.db.session() as s:
            self.assertEqual(s.execute(text("SELECT count(*) FROM pg_extension WHERE extname='pg_trgm'")).scalar(), 1)


if __name__ == "__main__":
    unittest.main()
