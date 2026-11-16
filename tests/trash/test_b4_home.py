"""B4-5: 홈 할 일과 학생 목록."""
import unittest

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.settings import Settings
from tests.trash.test_b4_trash_list import TEST_URL, TrashListTest as _Base


class UnitTest(unittest.TestCase):
    def test_routes(self):
        paths = create_app(Settings()).openapi()["paths"]
        self.assertIn("/v1/home", paths)
        self.assertIn("/v1/students", paths)


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class HomeTest(_Base):
    def test_home_counts_and_next_problem(self):
        empty = {"needs_review": 0, "recognizing": 0, "failed": 0, "next_problem": None}
        self.assertEqual(self.c.get("/v1/home").json(), {"todo": empty})
        exam_id, _, ids = self._exam(2, student="민수")
        todo = self.c.get("/v1/home").json()["todo"]
        self.assertEqual((todo["needs_review"], todo["recognizing"], todo["failed"]), (2, 0, 0))
        nxt = todo["next_problem"]
        self.assertEqual(nxt["exam_id"], exam_id)
        self.assertIn(nxt["problem_id"], ids)
        self.assertEqual(self.c.get(f"/v1/problems/{nxt['problem_id']}/neighbors?exam_id={exam_id}").json()["index"], 1)
        self.assertEqual(self.c.delete(f"/v1/problems/{nxt['problem_id']}").status_code, 204)
        todo = self.c.get("/v1/home").json()["todo"]
        self.assertEqual(todo["needs_review"], 1)
        self.assertNotEqual(todo["next_problem"]["problem_id"], nxt["problem_id"])
        self.assertEqual(self.c.delete(f"/v1/exams/{exam_id}").status_code, 204)
        self.assertEqual(self.c.get("/v1/home").json(), {"todo": empty})

    def test_home_owner_isolation(self):
        self._exam(1, student="민수")
        other = TestClient(create_app(Settings(database_url=TEST_URL, default_owner_id="o2"), store=self.store))
        self.assertEqual(other.get("/v1/home").json()["todo"]["needs_review"], 0)
        self.assertEqual(other.get("/v1/students").json(), {"items": []})

    def test_students(self):
        self._exam(0, student="영희")
        self._exam(0, student="민수")
        self._exam(0, title="무제")                                   # 학생 없음
        gone, _, _ = self._exam(0, student="철수")
        self.assertEqual(self.c.delete(f"/v1/exams/{gone}").status_code, 204)
        self.assertEqual(self.c.post("/v1/worksheets", json={"title": "오답", "student": "민수"}).status_code, 201)
        self.assertEqual(self.c.post("/v1/worksheets", json={"title": "복습", "student": "지수"}).status_code, 201)
        self.assertEqual(self.c.get("/v1/students").json(), {"items": ["민수", "영희", "지수"]})


# 부모 클래스의 B4-2 테스트가 다시 돌지 않게 하고, 부모 클래스는 모듈에서 뺀다
HomeTest.test_exam_delete_lists_only_the_exam = None
HomeTest.test_independent_deletes_and_type_filter = None
HomeTest.test_owner_isolation = None
del _Base

if __name__ == "__main__":
    unittest.main()
