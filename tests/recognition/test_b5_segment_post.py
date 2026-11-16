"""B5-2b-1: 분할 출력 후처리(좌표 변환, 합집합, 작은 칸, 겹침, 읽는 순서, 번호)."""
import json
import unittest

from app.recognition.ports import SegmentDraft
from app.recognition.vision.segment_post import SegmentParseError, segments_from_llm


def out(*problems):
    return json.dumps({"problems": list(problems)})


def P(number, box, choices=None, figure=None):
    return {"number": number, "box_2d": box, "choices_box_2d": choices, "figure_box_2d": figure}


class SegmentPostTest(unittest.TestCase):
    def test_converts_coordinates_and_keeps_sub_boxes(self):
        (s,) = segments_from_llm(out(P("12", [100, 50, 300, 480], [250, 60, 300, 470])))
        self.assertIsInstance(s, SegmentDraft)
        self.assertEqual(s.bbox, (0.05, 0.1, 0.48, 0.3))
        self.assertEqual(s.choices_bbox, (0.06, 0.25, 0.47, 0.3))
        self.assertIsNone(s.figure_bbox)
        self.assertEqual(s.number, "12")

    def test_union_includes_choices_and_figure(self):
        (s,) = segments_from_llm(out(P("1", [100, 50, 200, 480], [400, 50, 450, 480], [200, 300, 400, 480])))
        self.assertEqual(s.bbox, (0.05, 0.1, 0.48, 0.45))

    def test_clamps_and_skips_bad_boxes(self):
        segs = segments_from_llm(out(P("1", [-50, -10, 300, 2000]), P("2", [300, 100, 200, 400]),
                                     P("3", [1, 2, 3]), P("4", None), "x"))
        self.assertEqual([s.number for s in segs], ["1"])
        self.assertEqual(segs[0].bbox, (0.0, 0.0, 1.0, 0.3))

    def test_drops_tiny_boxes(self):
        segs = segments_from_llm(out(P("1", [100, 50, 300, 480]), P("2", [500, 50, 510, 100])))
        self.assertEqual([s.number for s in segs], ["1"])

    def test_heavy_overlap_merges(self):
        segs = segments_from_llm(out(P(None, [100, 50, 300, 480]), P("5", [120, 50, 320, 480])))
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].number, "5")
        self.assertEqual(segs[0].bbox, (0.05, 0.1, 0.48, 0.32))

    def test_slight_overlap_splits_at_middle(self):
        a, b = segments_from_llm(out(P("1", [100, 50, 300, 480]), P("2", [290, 50, 500, 480])))
        self.assertEqual((a.number, b.number), ("1", "2"))
        self.assertEqual(a.bbox[3], 0.295)
        self.assertEqual(b.bbox[1], 0.295)

    def test_reading_order_two_columns(self):
        segs = segments_from_llm(out(P("R2", [500, 520, 700, 950]), P("L2", [400, 50, 600, 480]),
                                     P("R1", [100, 520, 300, 950]), P("L1", [100, 50, 300, 480])))
        self.assertEqual([s.number for s in segs], ["L1", "L2", "R1", "R2"])

    def test_number_is_passed_through_or_none(self):
        segs = segments_from_llm(out(P(7, [100, 50, 300, 480]), P("", [400, 50, 600, 480]),
                                     P("01", [700, 50, 900, 480])))
        self.assertEqual([s.number for s in segs], ["7", None, "01"])

    def test_code_fence_and_empty(self):
        self.assertEqual(segments_from_llm("```json\n" + out(P("1", [100, 50, 300, 480])) + "\n```")[0].number, "1")
        self.assertEqual(segments_from_llm(out()), [])

    def test_bad_output_raises_parse_error(self):
        for bad in ("not json", "[]", json.dumps({"problems": "x"}), ""):
            with self.assertRaises(SegmentParseError):
                segments_from_llm(bad)


if __name__ == "__main__":
    unittest.main()
