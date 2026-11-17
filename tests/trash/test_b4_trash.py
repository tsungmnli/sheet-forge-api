"""B4-1: 시험지·사진 삭제가 문제도 휴지통으로 보낸다(deleted_with). DB 통합 테스트는 SHEET_FORGE_TEST_DATABASE_URL이 있을 때만 돈다.
복사 위치: tests/test_b4_trash.py"""
import os
import unittest
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


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class TrashCascadeTest(unittest.TestCase):
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

    def _exam(self, n=3):
        """시험지 1건·사진 1장, 문제 n개를 읽고 모두 확인 완료. (exam_id, page_id, 문제 id 목록)"""
        c = self.c
        exam = c.post("/exams", json={"student": "민수"}).json()
        r = c.post(f"/exams/{exam['id']}/pages", files=[("files", ("p.png", make_png(40, 30), "image/png"))])
        self.assertEqual(r.status_code, 202)
        page_id = r.json()["items"][0]["id"]
        self.assertTrue(run_once(self.db, self.store, FakePageProcessor(), recognizer=FakeRecognizer(),
                                 cleaner=FakeFigureCleaner()))
        for s in c.get(f"/pages/{page_id}").json()["segments"][:n]:
            self.assertEqual(c.patch(f"/pages/{page_id}/segments/{s['id']}", json={"marked": True}).status_code, 200)
        self.assertEqual(c.post(f"/exams/{exam['id']}/read").status_code, 202)
        for _ in range(n):
            self.assertTrue(run_once(self.db, self.store, FakePageProcessor(), recognizer=FakeRecognizer(),
                                     cleaner=FakeFigureCleaner()))
        ids = [i["problem_id"] for i in c.get(f"/exams/{exam['id']}/problems").json()["items"] if i["problem_id"]]
        self.assertEqual(len(ids), n)
        for pid in ids:
            v = c.get(f"/problems/{pid}").json()["version"]
            self.assertEqual(c.post(f"/problems/{pid}/confirm", headers=H(v)).status_code, 200)
        return exam["id"], page_id, ids

    def _problem_marks(self):
        """{problem_id: (삭제됨?, deleted_with)}"""
        with self.db.session() as s:
            rows = s.execute(text("SELECT id, deleted_at IS NOT NULL, deleted_with FROM problems")).all()
        return {r[0]: (r[1], r[2]) for r in rows}

    def test_exam_delete_trashes_problems(self):
        exam_id, _, ids = self._exam()
        ws = self.c.post("/worksheets", json={"problem_ids": ids}).json()
        self.assertEqual(self.c.delete(f"/exams/{exam_id}").status_code, 204)
        marks = self._problem_marks()
        self.assertEqual({marks[i] for i in ids}, {(True, exam_id)})
        for pid in ids:
            self.assertEqual(self.c.get(f"/problems/{pid}").status_code, 404)
        self.assertEqual(self.c.get("/problems").json()["items"], [])
        items = self.c.get(f"/worksheets/{ws['id']}").json()["items"]
        self.assertEqual([i["deleted"] for i in items], [True, True, True])   # 문제지에는 '삭제된 문제'로 남는다

    def test_separately_deleted_problem_keeps_its_own_mark(self):
        exam_id, _, ids = self._exam()
        self.assertEqual(self.c.delete(f"/problems/{ids[0]}").status_code, 204)
        self.assertEqual(self.c.delete(f"/exams/{exam_id}").status_code, 204)
        marks = self._problem_marks()
        self.assertEqual(marks[ids[0]], (True, None))            # 따로 지운 문제는 시험지 복구 때 되살아나면 안 된다
        self.assertEqual({marks[i] for i in ids[1:]}, {(True, exam_id)})

    def test_page_delete_trashes_its_problems_and_segments(self):
        exam_id, page_id, ids = self._exam()
        self.assertEqual(self.c.delete(f"/pages/{page_id}").status_code, 204)
        self.assertEqual({self._problem_marks()[i] for i in ids}, {(True, page_id)})
        with self.db.session() as s:
            segs = s.execute(text("SELECT DISTINCT deleted_with FROM segments WHERE page_id = :p"), {"p": page_id}).all()
        self.assertEqual({r[0] for r in segs}, {page_id})
        self.assertEqual(self.c.get(f"/exams/{exam_id}").status_code, 200)   # 시험지는 그대로
        self.assertEqual(self.c.delete(f"/exams/{exam_id}").status_code, 204)
        self.assertEqual({self._problem_marks()[i] for i in ids}, {(True, page_id)})   # 이미 지운 것은 덮어쓰지 않는다


if __name__ == "__main__":
    unittest.main()
