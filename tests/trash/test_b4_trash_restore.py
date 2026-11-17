"""B4-3: 휴지통 복구 (DB 통합 테스트)."""
import unittest

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.settings import Settings
from tests.trash.test_b4_trash_list import TEST_URL, TrashListTest as _Base


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class TrashRestoreTest(_Base):
    def _alive(self, pid):
        return self.c.get(f"/problems/{pid}").status_code == 200

    def test_exam_restore_only_what_was_deleted_with_it(self):
        exam_id, _, ids = self._exam(2)
        self.assertEqual(self.c.delete(f"/problems/{ids[0]}").status_code, 204)       # 따로 지운 문제
        self.assertEqual(self.c.delete(f"/exams/{exam_id}").status_code, 204)
        r = self.c.post(f"/trash/problem/{ids[0]}/restore")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "PARENT_IN_TRASH"))
        r = self.c.post(f"/trash/exam/{exam_id}/restore")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["restored"]["problem"], 1)
        self.assertTrue(self._alive(ids[1]))
        self.assertFalse(self._alive(ids[0]))                                              # 따로 지운 것은 그대로
        self.assertEqual(self.c.post(f"/trash/problem/{ids[0]}/restore").status_code, 200)
        self.assertTrue(self._alive(ids[0]))
        self.assertEqual(self.c.post(f"/trash/problem/{ids[0]}/restore").status_code, 404)   # 이미 복구됨

    def test_page_restore_and_parent_in_trash(self):
        exam_id, page_id, ids = self._exam(2)
        self.assertEqual(self.c.delete(f"/pages/{page_id}").status_code, 204)
        self.assertFalse(self._alive(ids[0]))
        self.assertEqual(self.c.delete(f"/exams/{exam_id}").status_code, 204)
        r = self.c.post(f"/trash/page/{page_id}/restore")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "PARENT_IN_TRASH"))
        self.assertEqual(self.c.post(f"/trash/exam/{exam_id}/restore").status_code, 200)
        self.assertEqual(self.c.post(f"/trash/page/{page_id}/restore").status_code, 200)
        self.assertTrue(all(self._alive(i) for i in ids))

    def test_worksheet_restore_isolation_and_bad_type(self):
        ws = self.c.post("/worksheets", json={"title": "오답"}).json()
        self.assertEqual(self.c.delete(f"/worksheets/{ws['id']}").status_code, 204)
        other = TestClient(create_app(Settings(database_url=TEST_URL, default_owner_id="o2"), store=self.store))
        self.assertEqual(other.post(f"/trash/worksheet/{ws['id']}/restore").status_code, 404)
        self.assertEqual(self.c.post(f"/trash/worksheet/{ws['id']}/restore").status_code, 200)
        self.assertEqual(self.c.get(f"/worksheets/{ws['id']}").status_code, 200)
        self.assertEqual(self.c.post(f"/trash/segment/{ws['id']}/restore").status_code, 404)


# 부모 클래스의 B4-2 테스트가 다시 돌지 않게 하고, 부모 클래스는 모듈에서 뺀다
TrashRestoreTest.test_exam_delete_lists_only_the_exam = None
TrashRestoreTest.test_independent_deletes_and_type_filter = None
TrashRestoreTest.test_owner_isolation = None
del _Base

if __name__ == "__main__":
    unittest.main()
