"""B4-6d: 정기 정리 실행 (DB 통합 테스트)."""
import unittest
from datetime import datetime, timedelta, timezone

from app.worker.maintenance import run_maintenance
from tests.trash.test_b4_trash_list import TEST_URL, TrashListTest as _Base


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class MaintenanceTest(_Base):
    def test_run_maintenance_purges_expired_trash(self):
        exam_id, _, _ = self._exam(1)
        keep, _, _ = self._exam(0, title="남길 시험지")
        before = set(self.store.objects)
        self.assertEqual(self.c.delete(f"/exams/{exam_id}").status_code, 204)
        now = datetime.now(timezone.utc)
        res = run_maintenance(self.db, self.store, 30, now + timedelta(days=10))      # 아직 보존 기간 안
        self.assertEqual(res["trash"]["counts"]["exam"], 0)
        self.assertEqual(set(self.store.objects), before)
        res = run_maintenance(self.db, self.store, 30, now + timedelta(days=31))      # 보존 기간이 지남
        self.assertEqual(res["trash"]["counts"]["exam"], 1)
        self.assertEqual(self.c.get("/trash").json()["items"], [])
        self.assertEqual(self.c.get(f"/exams/{keep}").status_code, 200)            # 살아 있는 시험지는 그대로
        self.assertEqual(res["originals"]["pages"], 0)                                  # 가짜 처리기 사진(보정본=원본)은 건너뜀


# 부모 클래스의 B4-2 테스트가 다시 돌지 않게 하고, 부모 클래스는 모듈에서 뺀다
MaintenanceTest.test_exam_delete_lists_only_the_exam = None
MaintenanceTest.test_independent_deletes_and_type_filter = None
MaintenanceTest.test_owner_isolation = None
del _Base

if __name__ == "__main__":
    unittest.main()
