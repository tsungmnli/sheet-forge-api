"""읽기 결과의 그림 상자를 그림 항목으로 바꾸는 순수 함수."""
import unittest

from app.worker.problems import FIGURE_WIDTH_MM, figures_from_read


class FiguresFromReadTest(unittest.TestCase):
    def test_converts_box_to_bbox(self):
        out = figures_from_read([{"box_2d": [100, 200, 600, 800], "placement": "after_choices"}])
        self.assertEqual(len(out), 1)
        f = out[0]
        self.assertEqual(f["bbox"], [0.2, 0.1, 0.8, 0.6])
        self.assertEqual((f["placement"], f["state"], f["use"], f["width_mm"]),
                         ("after_choices", "processing", "clean", FIGURE_WIDTH_MM))
        self.assertTrue(f["id"].startswith("fig"))
        self.assertIsNone(f["raw_ref"])
        self.assertIsNone(f["clean_ref"])

    def test_clamps_and_skips_bad_boxes(self):
        out = figures_from_read([
            {"box_2d": [-50, -10, 1100, 1200]},      # 범위 밖 -> 0~1로 자름
            {"box_2d": [500, 500, 505, 900]},        # 너무 낮음
            {"box_2d": [600, 100, 200, 300]},        # 뒤집힘
            {"box_2d": [1, 2, 3]},                   # 길이 틀림
            {"placement": "after_stem"},             # 상자 없음
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bbox"], [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(out[0]["placement"], "after_stem")

    def test_empty(self):
        self.assertEqual(figures_from_read(None), [])
        self.assertEqual(figures_from_read([]), [])


if __name__ == "__main__":
    unittest.main()
