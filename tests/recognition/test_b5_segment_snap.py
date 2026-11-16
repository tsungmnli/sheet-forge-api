"""B5-2b-3: 가장자리 맞춤(합성 이미지: 흰 바탕에 글줄 모양의 검은 띠)."""
import unittest

import numpy as np

from app.recognition.ports import SegmentDraft
from app.recognition.vision.segment_snap import snap_segments


def page(lines, x0=100, x1=400, size=1000):
    g = np.full((size, size), 255, np.uint8)
    for a, b in lines:
        g[a:b, x0:x1] = 0
    return g


def seg(box, number="1"):
    return SegmentDraft(bbox=box, number=number)


class SnapTest(unittest.TestCase):
    def test_top_edge_cutting_a_line_moves_up_to_include_it(self):
        g = page([(100, 112), (130, 142)])
        (s,) = snap_segments(g, [seg((0.05, 0.105, 0.45, 0.2))], top_pad=0.0)
        self.assertLessEqual(s.bbox[1] * 1000, 100)
        self.assertGreater(s.bbox[1] * 1000, 70)

    def test_bottom_edge_cutting_a_line_moves_down_to_include_it(self):
        g = page([(100, 112), (130, 142)])
        (s,) = snap_segments(g, [seg((0.05, 0.05, 0.45, 0.136))], top_pad=0.0)
        self.assertGreaterEqual(s.bbox[3] * 1000, 142)
        self.assertLess(s.bbox[3] * 1000, 175)

    def test_edges_already_in_whitespace_stay(self):
        g = page([(100, 112), (130, 142)])
        (s,) = snap_segments(g, [seg((0.05, 0.08, 0.45, 0.2))], top_pad=0.0)
        self.assertEqual(s.bbox, (0.05, 0.08, 0.45, 0.2))

    def test_right_edge_cutting_text_moves_out(self):
        g = page([(100, 112), (130, 142)])
        (s,) = snap_segments(g, [seg((0.05, 0.09, 0.395, 0.2))], top_pad=0.0)
        self.assertGreaterEqual(s.bbox[2] * 1000, 400)
        self.assertEqual(s.bbox[0], 0.05)

    def test_default_adds_top_padding_and_keeps_number_and_sub_boxes(self):
        g = page([(100, 112)])
        d = SegmentDraft(bbox=(0.05, 0.1, 0.45, 0.2), number="7", choices_bbox=(0.05, 0.15, 0.45, 0.2))
        (s,) = snap_segments(g, [d])
        self.assertLess(s.bbox[1], 0.1)
        self.assertEqual((s.number, s.choices_bbox), ("7", (0.05, 0.15, 0.45, 0.2)))

    def test_page_border_and_blank_page_and_empty_list(self):
        g = page([(100, 112)])
        (s,) = snap_segments(g, [seg((0.0, 0.0, 1.0, 1.0))])
        self.assertEqual(s.bbox, (0.0, 0.0, 1.0, 1.0))
        blank = np.full((500, 500), 255, np.uint8)
        d = seg((0.1, 0.1, 0.5, 0.5))
        self.assertEqual(snap_segments(blank, [d]), [d])
        self.assertEqual(snap_segments(g, []), [])

    def test_order_is_kept(self):
        g = page([(100, 112), (400, 412)])
        out = snap_segments(g, [seg((0.05, 0.3, 0.45, 0.5), "B"), seg((0.05, 0.05, 0.45, 0.2), "A")])
        self.assertEqual([s.number for s in out], ["B", "A"])


if __name__ == "__main__":
    unittest.main()
