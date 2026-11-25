"""4단계: stem의 box·table 블록 — 검증·저장 모양·조각 경로·요약·수정 통계·스키마 직렬화. DB 없음."""
import unittest

from app.api import edit_stats, problem_logic as pl
from app.api.errors import ApiError
from app.api.schemas import ContentIn
from app.api.schemas_problem import ContentOut
from app.api.schemas_web import ContentPutBody


def t(v):
    return {"t": "text", "v": v}


def m(latex):
    return {"t": "math", "latex": latex}


def box(*lines, title="<보기>"):
    return {"type": "box", "title": title, "paragraphs": [{"inlines": list(x)} for x in lines]}


def table(*rows):
    return {"type": "table", "rows": [list(r) for r in rows]}


def content(*stem):
    return {"stem": list(stem), "choices": {"items": [[t("ㄱ")]], "layout": "auto"}, "figures": []}


class Paths(unittest.TestCase):
    def test_iter_inlines_paths(self):
        c = content({"type": "paragraph", "inlines": [t("문제")]},
                    box([t("ㄱ. "), m("a")], [t("ㄴ.")]),
                    table([[t("x")], [m("1")]], [[t("y")], []]))
        paths = [p for p, _ in pl.iter_inlines(c)]
        self.assertEqual(paths, ["stem/0/inlines/0",
                                 "stem/1/paragraphs/0/inlines/0", "stem/1/paragraphs/0/inlines/1",
                                 "stem/1/paragraphs/1/inlines/0",
                                 "stem/2/rows/0/0/0", "stem/2/rows/0/1/0", "stem/2/rows/1/0/0",
                                 "choices/items/0/0"])

    def test_search_text_and_preview_include_box_and_table(self):
        c = content({"type": "paragraph", "inlines": [t("문제")]}, box([t("ㄱ. 가")], [t("ㄴ. 나")]),
                    table([[t("합계")], [m("1")]]))
        for s in (pl.search_text(c), pl.preview(c), pl.preview_tex(c)):
            self.assertIn("ㄱ. 가", s)
            self.assertIn("ㄴ. 나", s)
            self.assertIn("합계", s)
        self.assertIn("ㄱ. 가 ㄴ. 나", pl.preview(c))        # 상자 줄 사이에 공백
        self.assertIn("$1$", pl.preview_tex(c))

    def test_paragraph_only_preview_unchanged(self):
        c = content({"type": "paragraph", "inlines": [t("가")]}, {"type": "paragraph", "inlines": [t("나")]})
        self.assertEqual(pl.preview(c), "가나")                # 기존 동작(문단 사이 공백 없음) 유지


class Analyze(unittest.TestCase):
    def test_blocker_path_points_into_box_and_table(self):
        c = content(box([m("")]), table([[m("")]]))
        c["choices"]["items"] = []
        _, blockers, has = pl.analyze(c)
        self.assertEqual(sorted(b["path"] for b in blockers), ["stem/0/paragraphs/0/inlines/0", "stem/1/rows/0/0/0"])
        self.assertFalse(has)

    def test_has_content_from_box(self):
        self.assertTrue(pl.analyze(content(box([t("ㄱ")])))[2])


class Normalize(unittest.TestCase):
    def norm(self, c):
        return pl.normalize_content(ContentIn.model_validate(c))

    def test_box_without_title_is_titleless_and_inlines_dropped(self):
        out = self.norm(content({"type": "box", "paragraphs": [{"inlines": [t("ㄱ")]}]}))
        b = out["stem"][0]
        self.assertEqual((b["type"], b["title"]), ("box", ""))
        self.assertNotIn("inlines", b)

    def test_box_title_kept_or_blanked(self):
        self.assertEqual(self.norm(content(box([t("ㄱ")])))["stem"][0]["title"], "<보기>")
        self.assertEqual(self.norm(content(box([t("ㄱ")], title="  ")))["stem"][0]["title"], "")

    def test_table_padded_rectangular(self):
        out = self.norm(content(table([[t("a")], [t("b")], [t("c")]], [[t("d")]])))
        rows = out["stem"][0]["rows"]
        self.assertEqual([len(r) for r in rows], [3, 3])
        self.assertEqual(rows[1][2], [])

    def test_paragraph_block_untouched(self):
        out = self.norm(content({"type": "paragraph", "inlines": [t("가")]}))
        self.assertEqual(out["stem"][0], {"type": "paragraph", "inlines": [{"t": "text", "v": "가"}]})

    def test_inline_checks_reach_box_and_table(self):
        with self.assertRaises(ApiError):
            self.norm(content(box([{"t": "bogus"}])))
        with self.assertRaises(ApiError):
            self.norm(content(table([[{"t": "bogus"}]])))
        with self.assertRaises(ApiError):
            self.norm(content(box([t("x" * (pl.MAX_TEXT + 1))])))

    def test_limits(self):
        from app.api import stem_blocks as sb
        with self.assertRaises(ApiError):
            self.norm(content(box(*[[t("a")]] * (sb.MAX_BOX_LINES + 1))))
        with self.assertRaises(ApiError):
            self.norm(content(table(*[[[t("a")]]] * (sb.MAX_TABLE_ROWS + 1))))
        with self.assertRaises(ApiError):
            self.norm(content(table([[t("a")]] * (sb.MAX_TABLE_COLS + 1))))
        with self.assertRaises(ApiError):
            self.norm(content(box([t("a")], title="가" * (sb.MAX_TITLE + 1))))

    def test_total_inline_limit_counts_table_cells(self):
        cells = [[t("a")]] * 8
        with self.assertRaises(ApiError):
            self.norm(content(*[table(cells)] * 40))      # 320 조각 > MAX_INLINES

    def test_unknown_block_type_still_accepted(self):
        out = self.norm(content({"type": "mystery", "inlines": [t("가")]}))
        self.assertEqual(out["stem"][0]["type"], "mystery")

    def test_export_roundtrip_shape(self):
        """저장 모양 그대로 내보내기에 들어가 상자·표가 나온다."""
        from app.export.hwpx import ExportMeta, ExportRequest, export_hwpx
        out = self.norm(content(box([t("ㄱ. 가")]), table([[t("a")], [m("1")]])))
        r = export_hwpx(ExportRequest([{"id": "p", "status": "confirmed", "content": out}], None, ExportMeta("t")))
        self.assertEqual((r.report.stats["boxes"], r.report.stats["tables"]), (1, 1))


class Schemas(unittest.TestCase):
    def test_out_paragraph_block_has_no_new_keys(self):
        d = ContentOut.model_validate(content({"type": "paragraph", "inlines": [t("가")]})).model_dump()
        self.assertEqual(set(d["stem"][0]), {"type", "inlines"})

    def test_out_box_and_table_roundtrip(self):
        c = content(box([t("ㄱ")]), table([[t("a")], [m("1")]]))
        d = ContentOut.model_validate(c).model_dump()
        self.assertEqual(set(d["stem"][0]), {"type", "title", "paragraphs"})
        self.assertEqual(set(d["stem"][1]), {"type", "rows"})
        self.assertEqual(d["stem"][1]["rows"][0][1][0]["latex"], "1")

    def test_put_body_accepts_box_and_table(self):
        b = ContentPutBody.model_validate(content(box([t("ㄱ")]), table([[t("a")]])))
        self.assertEqual(b.stem[0].paragraphs[0].inlines[0].v, "ㄱ")
        self.assertEqual(b.stem[1].rows[0][0][0].v, "a")


class EditStats(unittest.TestCase):
    def test_box_and_table_edits_counted(self):
        a = content(box([t("ㄱ. 가")], [t("ㄴ. 나")]), table([[t("1")], [t("2")]]))
        same = edit_stats.count_edits(a, a)
        self.assertEqual(sum(same["edited"].values()), 0)
        b = content(box([t("ㄱ. 가")], [t("ㄴ. 다")]), table([[t("1")], [t("3")]]))
        d = edit_stats.count_edits(a, b)
        self.assertEqual(d["edited"]["text"], 2)
        self.assertGreater(d["of"]["text"], 2)


if __name__ == "__main__":
    unittest.main()
