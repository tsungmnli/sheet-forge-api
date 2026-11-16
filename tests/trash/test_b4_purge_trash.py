"""B4-6a: 휴지통 영구 삭제 함수 (DB 통합 테스트)."""
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.purge import purge_trash
from tests.trash.test_b4_trash_list import TEST_URL, TrashListTest as _Base


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class PurgeTrashTest(_Base):
    def _age(self, days):
        with self.db.session() as s:
            for t in ("exams", "pages", "segments", "problems", "worksheets"):
                s.execute(text(f"UPDATE {t} SET deleted_at = now() - make_interval(days => :d) WHERE deleted_at IS NOT NULL"), {"d": days})
            s.commit()

    def _purge(self, days=30):
        with self.db.session() as s:
            return purge_trash(s, datetime.now(timezone.utc) - timedelta(days=days))

    def _count(self, table):
        with self.db.session() as s:
            return s.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()

    def test_expired_exam_is_purged_with_children_and_leaves_worksheet(self):
        exam_id, _, ids = self._exam(2)
        ws = self.c.post("/v1/worksheets", json={"title": "오답", "problem_ids": ids}).json()
        self.assertEqual(self.c.delete(f"/v1/exams/{exam_id}").status_code, 204)
        self._age(31)
        res = self._purge()
        self.assertEqual((res["counts"]["exam"], res["counts"]["page"], res["counts"]["problem"]), (1, 1, 2))
        self.assertTrue(res["counts"]["segment"] >= 2)
        self.assertTrue(res["refs"])                                   # 지운 행이 쓰던 이미지 ref 후보
        self.assertEqual([self._count(t) for t in ("exams", "pages", "problems", "segments", "worksheet_items")], [0] * 5)
        self.assertEqual(self.c.get(f"/v1/worksheets/{ws['id']}").json()["items"], [])   # 문제지는 남고 목록만 빠짐
        self.assertEqual(self._purge()["counts"], {"problem": 0, "segment": 0, "page": 0, "exam": 0, "worksheet": 0})   # 멱등

    def test_not_expired_is_kept(self):
        exam_id, _, ids = self._exam(1)
        ws = self.c.post("/v1/worksheets", json={"title": "오답"}).json()
        self.assertEqual(self.c.delete(f"/v1/exams/{exam_id}").status_code, 204)
        self.assertEqual(self.c.delete(f"/v1/worksheets/{ws['id']}").status_code, 204)
        self._age(29)
        self.assertEqual(sum(self._purge()["counts"].values()), 0)
        self.assertEqual(len(self.c.get("/v1/trash").json()["items"]), 2)

    def test_individually_deleted_problem_and_worksheet(self):
        exam_id, _, ids = self._exam(2)
        ws = self.c.post("/v1/worksheets", json={"title": "오답", "problem_ids": ids}).json()
        self.assertEqual(self.c.delete(f"/v1/problems/{ids[0]}").status_code, 204)
        self._age(31)
        self.assertEqual(self._purge()["counts"]["problem"], 1)
        items = self.c.get(f"/v1/worksheets/{ws['id']}").json()["items"]
        self.assertEqual([i["problem_id"] for i in items], [ids[1]])
        self.assertEqual(self.c.get(f"/v1/problems/{ids[1]}").status_code, 200)       # 살아 있는 문제는 그대로
        self.assertEqual(self.c.delete(f"/v1/worksheets/{ws['id']}").status_code, 204)
        self._age(31)
        self.assertEqual(self._purge()["counts"]["worksheet"], 1)
        self.assertEqual(self._count("worksheets"), 0)


# 부모 클래스의 B4-2 테스트가 다시 돌지 않게 하고, 부모 클래스는 모듈에서 뺀다
PurgeTrashTest.test_exam_delete_lists_only_the_exam = None
PurgeTrashTest.test_independent_deletes_and_type_filter = None
PurgeTrashTest.test_owner_isolation = None
del _Base

if __name__ == "__main__":
    unittest.main()
