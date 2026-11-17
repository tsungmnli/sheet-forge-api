"""B3 2단계: 문제지 CRUD·담기·순서·번호. DB 통합 테스트는 SHEET_FORGE_TEST_DATABASE_URL이 있을 때만 돈다.
복사 위치: tests/test_b3.py"""
import copy
import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.main import create_app
from app.api.settings import Settings
from app.api.worksheet_service import assign_numbers
from app.db.database import Database
from app.recognition.fake import FakeFigureCleaner, FakePageProcessor, FakeRecognizer
from app.storage.images import MemoryImageStore
from app.worker.main import run_once
from tests.api.test_b2 import make_png

TEST_URL = os.environ.get("SHEET_FORGE_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parent.parent.parent


def H(v):
    return {"If-Match": f'"{v}"'}


class UnitTest(unittest.TestCase):
    def test_assign_numbers(self):
        flags = [(False, "confirmed"), (False, "needs_review"), (True, "confirmed"), (False, "confirmed")]
        preset = {"numbering": {"format": "{n:02d}", "start": 5}}
        self.assertEqual(assign_numbers(flags, preset, "skip"), ["05", None, None, "06"])
        self.assertEqual(assign_numbers(flags, preset, "fail"), ["05", "06", None, "07"])
        self.assertEqual(assign_numbers(flags, {}, "skip"), ["01", None, None, "02"])   # 기본 형식
        self.assertEqual(assign_numbers([(False, "confirmed")], {"numbering": {"format": "{x}"}}, "skip"), ["1"])

    def test_openapi_has_worksheet_routes(self):
        paths = create_app(Settings()).openapi()["paths"]
        for p in ("/worksheets", "/worksheets/{worksheet_id}", "/worksheets/{worksheet_id}/problems",
                  "/worksheets/{worksheet_id}/duplicate"):
            self.assertIn(p, paths)


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class WorksheetFlowTest(unittest.TestCase):
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

    def _client(self, owner="o1", **settings):
        return TestClient(create_app(Settings(database_url=TEST_URL, default_owner_id=owner, **settings),
                                     store=self.store))

    def _exam(self, n=3, confirm=2):
        """시험지 1건, 문제 n개를 읽고 앞에서 confirm개를 확인 완료. (exam_id, 문제 id 목록(사진 순서))"""
        c = self.c = self._client()
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
        for pid in ids[:confirm]:
            v = c.get(f"/problems/{pid}").json()["version"]
            r = c.post(f"/problems/{pid}/confirm", headers=H(v))
            self.assertEqual(r.status_code, 200, r.text)
        return exam["id"], ids

    def _ws(self, **body):
        r = self.c.post("/worksheets", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.headers["ETag"], f'"{r.json()["version"]}"')
        return r.json()

    def _numbers(self, ws):
        return [i["number"] for i in ws["items"]]

    def test_create_from_exam(self):
        exam_id, ids = self._exam()
        ws = self._ws(from_exam_id=exam_id)
        self.assertEqual([i["problem_id"] for i in ws["items"]], ids[:2])   # 확인 완료만, 사진 순서
        self.assertEqual(self._numbers(ws), ["01", "02"])
        self.assertEqual(ws["student"], "민수")
        self.assertEqual(ws["unconfirmed_policy"], "skip")
        self.assertNotIn("header", ws)   # 위쪽 제목칸은 MVP에서 뺐다
        self.assertGreater(ws["layout"]["body_w_mm"], 0)
        self.assertEqual(self._ws(from_exam_id=exam_id, student="영희")["student"], "영희")
        empty = self._ws()
        self.assertEqual((empty["items"], empty["title"], empty["student"]), ([], "", ""))
        r = self.c.post("/worksheets", json={"from_exam_id": exam_id, "problem_ids": ids})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.c.post("/worksheets", json={"from_exam_id": "exam_nope"}).status_code, 404)

    def test_create_with_problem_ids(self):
        _, ids = self._exam()
        ws = self._ws(problem_ids=[ids[1], ids[0], ids[1]])
        self.assertEqual([i["problem_id"] for i in ws["items"]], [ids[1], ids[0]])   # 중복은 무시, 순서 유지
        r = self.c.post("/worksheets", json={"problem_ids": [ids[0], "prob_nope"]})
        self.assertEqual(r.status_code, 404)

    def test_add_problems_and_policy_numbers(self):
        exam_id, ids = self._exam()
        ws = self._ws(from_exam_id=exam_id)
        r = self.c.post(f"/worksheets/{ws['id']}/problems", json={"problem_ids": [ids[2], ids[2], ids[0]]})
        self.assertEqual(r.status_code, 200, r.text)
        added = r.json()
        self.assertEqual([i["problem_id"] for i in added["items"]], ids)
        self.assertEqual(self._numbers(added), ["01", "02", None])          # 확인 안 끝난 문제는 번호 없음(skip)
        self.assertEqual(added["items"][2]["status"], "needs_review")
        self.assertGreater(added["version"], ws["version"])
        r = self.c.patch(f"/worksheets/{ws['id']}", json={"unconfirmed_policy": "fail"},
                         headers=H(added["version"]))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._numbers(r.json()), ["01", "02", "03"])
        self.assertEqual(self.c.patch(f"/worksheets/{ws['id']}", json={"title": "x"},
                                      headers=H(ws["version"])).status_code, 412)   # 낡은 version
        self.assertEqual(self.c.patch(f"/worksheets/{ws['id']}", json={"title": "x"}).status_code, 428)
        self.assertEqual(self.c.patch(f"/worksheets/{ws['id']}", json={}, headers=H(r.json()["version"]))
                         .status_code, 422)
        r = self.c.post(f"/worksheets/{ws['id']}/problems", json={"problem_ids": ["prob_nope"]})
        self.assertEqual(r.status_code, 404)

    def test_put_reorder_and_limits(self):
        exam_id, ids = self._exam()
        ws = self._ws(from_exam_id=exam_id)
        url = f"/worksheets/{ws['id']}/problems"
        r = self.c.put(url, json={"problem_ids": [ids[1], ids[0]]}, headers=H(ws["version"]))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([i["problem_id"] for i in r.json()["items"]], [ids[1], ids[0]])
        self.assertEqual(self.c.put(url, json={"problem_ids": [ids[0]]}, headers=H(ws["version"])).status_code, 412)
        self.assertEqual(self.c.put(url, json={"problem_ids": [ids[0]]}).status_code, 428)
        v = r.json()["version"]
        self.assertEqual(self.c.put(url, json={"problem_ids": ["prob_nope"]}, headers=H(v)).status_code, 404)
        r = self.c.put(url, json={"problem_ids": []}, headers=H(v))           # 전부 빼기
        self.assertEqual(r.json()["items"], [])
        small = self._client(max_problems=1)
        r = small.put(url, json={"problem_ids": ids[:2]}, headers=H(r.json()["version"]))
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (413, "TOO_MANY_PROBLEMS"))

    def test_patch_title_and_preset(self):
        exam_id, _ = self._exam()
        ws = self._ws(from_exam_id=exam_id)
        r = self.c.patch(f"/worksheets/{ws['id']}", headers=H(ws["version"]),
                         json={"title": "오답 문제지", "student": "철수"})
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual((out["title"], out["student"]), ("오답 문제지", "철수"))
        bad = copy.deepcopy(out["preset"])
        bad["columns"]["count"] = 9
        r = self.c.patch(f"/worksheets/{ws['id']}", json={"preset": bad}, headers=H(out["version"]))
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "PRESET_INVALID"))
        good = copy.deepcopy(out["preset"])
        good["columns"]["count"] = 2
        good["numbering"]["start"] = 5
        r = self.c.patch(f"/worksheets/{ws['id']}", json={"preset": good}, headers=H(out["version"]))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._numbers(r.json()), ["05", "06"])
        self.assertLess(r.json()["layout"]["col_w"], r.json()["layout"]["body_w"])

    def test_deleted_problem_stays_greyed(self):
        exam_id, ids = self._exam()
        ws = self._ws(from_exam_id=exam_id)
        r = self.c.delete(f"/problems/{ids[0]}")
        self.assertIn(r.status_code, (200, 204))
        got = self.c.get(f"/worksheets/{ws['id']}").json()
        self.assertEqual([(i["deleted"], i["number"]) for i in got["items"]], [(True, None), (False, "01")])
        self.assertEqual(self.c.get("/worksheets").json()["items"][0]["problem_count"], 1)
        r = self.c.post(f"/worksheets/{ws['id']}/problems", json={"problem_ids": [ids[0]]})
        self.assertEqual(r.status_code, 200)   # 이미 담긴 문제는 무시(삭제됐어도)
        self.assertEqual(self.c.delete(f"/problems/{ids[2]}").status_code, 204)
        r = self.c.post(f"/worksheets/{ws['id']}/problems", json={"problem_ids": [ids[2]]})
        self.assertEqual(r.status_code, 404)   # 지운 문제는 새로 못 담는다

    def test_duplicate_delete_list_owner(self):
        exam_id, ids = self._exam()
        ws = self._ws(from_exam_id=exam_id, title="중간")
        r = self.c.post(f"/worksheets/{ws['id']}/duplicate")
        self.assertEqual(r.status_code, 201, r.text)
        dup = r.json()
        self.assertNotEqual(dup["id"], ws["id"])
        self.assertEqual(dup["title"], "중간 복사본")
        self.assertEqual([i["problem_id"] for i in dup["items"]], ids[:2])
        listed = self.c.get("/worksheets").json()
        self.assertEqual({i["id"] for i in listed["items"]}, {ws["id"], dup["id"]})
        self.assertEqual({i["problem_count"] for i in listed["items"]}, {2})
        page1 = self.c.get("/worksheets?limit=1").json()
        self.assertEqual(len(page1["items"]), 1)
        self.assertEqual(len(self.c.get(f"/worksheets?limit=1&cursor={page1['next_cursor']}").json()["items"]), 1)
        other = self._client(owner="o2")
        self.assertEqual(other.get(f"/worksheets/{ws['id']}").status_code, 404)
        self.assertEqual(other.get("/worksheets").json()["items"], [])
        self.assertEqual(self.c.delete(f"/worksheets/{ws['id']}").status_code, 204)
        self.assertEqual(self.c.get(f"/worksheets/{ws['id']}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
