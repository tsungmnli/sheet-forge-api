"""B4-2: 휴지통 목록(GET /v1/trash). DB 통합 테스트는 SHEET_FORGE_TEST_DATABASE_URL이 있을 때만 돈다.
복사 위치: tests/test_b4_trash_list.py"""
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.main import create_app
from app.api.settings import Settings
from app.db.database import Database
from app.recognition.fake import FakeFigureCleaner, FakePageProcessor, FakeRecognizer
from app.storage.images import MemoryImageStore
from app.worker.main import run_once
from tests.api.test_b2 import make_png

TEST_URL = os.environ.get("SHEET_FORGE_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parent.parent.parent


def H(v):
    return {"If-Match": f'"{v}"'}


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class UnitTest(unittest.TestCase):
    def test_settings_and_route(self):
        self.assertEqual(Settings().trash_retention_days, 30)
        self.assertIn("/v1/trash", create_app(Settings()).openapi()["paths"])


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class TrashListTest(unittest.TestCase):
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
            s.execute(text("TRUNCATE jobs, worksheet_items, worksheets, export_presets, problems, read_usage, "
                           "segments, pages, exams CASCADE"))
            s.commit()
        self.store = MemoryImageStore()
        self.c = TestClient(create_app(Settings(database_url=TEST_URL, default_owner_id="o1"), store=self.store))

    def _exam(self, n=2, **body):
        c = self.c
        exam = c.post("/v1/exams", json=body or {"student": "민수"}).json()
        r = c.post(f"/v1/exams/{exam['id']}/pages", files=[("files", ("p.png", make_png(40, 30), "image/png"))])
        self.assertEqual(r.status_code, 202)
        page_id = r.json()["items"][0]["id"]
        if n:
            self.assertTrue(run_once(self.db, self.store, FakePageProcessor(), recognizer=FakeRecognizer(),
                                     cleaner=FakeFigureCleaner()))
            for s in c.get(f"/v1/pages/{page_id}").json()["segments"][:n]:
                self.assertEqual(c.patch(f"/v1/pages/{page_id}/segments/{s['id']}", json={"marked": True}).status_code, 200)
            self.assertEqual(c.post(f"/v1/exams/{exam['id']}/read").status_code, 202)
            for _ in range(n):
                self.assertTrue(run_once(self.db, self.store, FakePageProcessor(), recognizer=FakeRecognizer(),
                                         cleaner=FakeFigureCleaner()))
        ids = [i["problem_id"] for i in c.get(f"/v1/exams/{exam['id']}/problems").json()["items"] if i["problem_id"]]
        return exam["id"], page_id, ids

    def test_exam_delete_lists_only_the_exam(self):
        exam_id, _, ids = self._exam(2, title="중간고사", student="민수")
        self.assertEqual(self.c.get("/v1/trash").json()["items"], [])
        self.assertEqual(self.c.delete(f"/v1/exams/{exam_id}").status_code, 204)
        items = self.c.get("/v1/trash").json()["items"]
        self.assertEqual([(i["type"], i["id"], i["label"]) for i in items], [("exam", exam_id, "중간고사")])
        self.assertEqual(ts(items[0]["purge_at"]) - ts(items[0]["deleted_at"]), timedelta(days=30))

    def test_independent_deletes_and_type_filter(self):
        _, _, ids = self._exam(2, student="민수")
        self.assertEqual(self.c.delete(f"/v1/problems/{ids[0]}").status_code, 204)
        ws = self.c.post("/v1/worksheets", json={"title": "오답"}).json()
        self.assertEqual(self.c.delete(f"/v1/worksheets/{ws['id']}").status_code, 204)
        _, page2, _ = self._exam(0, title="기말", student="영희")
        self.assertEqual(self.c.delete(f"/v1/pages/{page2}").status_code, 204)
        items = self.c.get("/v1/trash").json()["items"]
        self.assertEqual([i["type"] for i in items], ["page", "worksheet", "problem"])   # 최근에 지운 순
        self.assertEqual(items[0]["label"], "기말의 사진 1")
        self.assertEqual(items[1]["label"], "오답")
        self.assertTrue(items[2]["label"])
        only = self.c.get("/v1/trash?type=worksheet").json()["items"]
        self.assertEqual([i["id"] for i in only], [ws["id"]])
        self.assertEqual(len(self.c.get("/v1/trash?limit=2").json()["items"]), 2)
        self.assertEqual(self.c.get("/v1/trash?type=segment").status_code, 422)
        self.assertEqual(self.c.get("/v1/trash?limit=0").status_code, 422)

    def test_owner_isolation(self):
        exam_id, _, _ = self._exam(0)
        self.assertEqual(self.c.delete(f"/v1/exams/{exam_id}").status_code, 204)
        other = TestClient(create_app(Settings(database_url=TEST_URL, default_owner_id="o2"), store=self.store))
        self.assertEqual(other.get("/v1/trash").json()["items"], [])


if __name__ == "__main__":
    unittest.main()
