"""사진 다시 보정하기: 꼭짓점 검증(순수 함수, DB 없음)."""
import unittest

from app.api.correction_service import check_corners
from app.api.errors import ApiError

OK = [[0.1, 0.1], [0.9, 0.12], [0.88, 0.9], [0.12, 0.88]]


class CheckCornersTest(unittest.TestCase):
    def test_accepts_convex_quad(self):
        self.assertEqual(len(check_corners(OK)), 4)

    def test_rejects_bad_input(self):
        bad = [None, OK[:3], [[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]],  # 꼬인 사각형
               [[0.0, 0.0], [0.1, 0.0], [0.1, 0.1], [0.0, 0.1]],                 # 너무 작음
               [[-0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]]                # 범위 밖
        for c in bad:
            with self.assertRaises(ApiError):
                check_corners(c)
