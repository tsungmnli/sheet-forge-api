"""출처 표기: none(안 찍음) / exam(시험지가 바뀌는 곳마다 한 줄) / problem(문항마다 번호 줄 끝)."""
import io
import unittest
import zipfile

from app.export.hwpx import ExportMeta, ExportRequest, export_hwpx
from app.export.hwpx.errors import PresetError
from app.export.hwpx.preset import ExportPreset

META = ExportMeta(title="출처")


def problem(pid, exam_id, label):
    return {"id": pid, "status": "confirmed", "exam_id": exam_id, "source_label": label, "content": {
        "stem": [{"type": "paragraph", "inlines": [{"t": "text", "v": f"{pid} 문제"}]}]}}


# A, A, B, A 순서. C는 출처를 적지 않은 시험지
PROBLEMS = [problem("p1", "A", "대안중 2025기말"), problem("p2", "A", "대안중 2025기말"),
            problem("p3", "B", "중앙중 2024중간"), problem("p4", "A", "대안중 2025기말"),
            problem("p5", "C", "")]


def section(mode):
    r = export_hwpx(ExportRequest(PROBLEMS, {"source": {"mode": mode}}, META))
    return zipfile.ZipFile(io.BytesIO(r.hwpx_bytes)).read("Contents/section0.xml").decode("utf-8")


class SourceLabelTest(unittest.TestCase):
    def test_default_is_none(self):
        self.assertEqual(ExportPreset().source.mode, "none")

    def test_unknown_mode_rejected(self):
        with self.assertRaises(PresetError):
            ExportPreset.from_dict({"source": {"mode": "page"}}).validate()

    def test_none_prints_nothing(self):
        x = section("none")
        self.assertNotIn("[대안중 2025기말]", x)
        self.assertNotIn("[중앙중 2024중간]", x)

    def test_exam_mode_prints_where_exam_changes(self):
        x = section("exam")
        # A 묶음 두 번(처음, B 뒤) + B 한 번. 출처 없는 C는 줄을 만들지 않는다
        self.assertEqual(x.count("<hp:t>[대안중 2025기말]</hp:t>"), 2)
        self.assertEqual(x.count("<hp:t>[중앙중 2024중간]</hp:t>"), 1)
        self.assertNotIn("[]", x)
        self.assertLess(x.index("[대안중 2025기말]"), x.index("p1 문제"))

    def test_problem_mode_appends_to_each_number(self):
        x = section("problem")
        self.assertEqual(x.count("[대안중 2025기말]"), 3)
        self.assertEqual(x.count("[중앙중 2024중간]"), 1)
        self.assertIn("01  [대안중 2025기말]", x)
        self.assertNotIn("[]", x)


if __name__ == "__main__":
    unittest.main()
