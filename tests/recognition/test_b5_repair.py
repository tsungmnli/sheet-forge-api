"""B5-3a-1: 읽기 결과 후처리(이스케이프 복구, 변수 수식화, 수식 안 한글 분리, 문단 합치기)."""
import unittest

from app.recognition.llm.repair import normalize_read


def T(v):
    return {"t": "text", "v": v, "latex": None}


def M(s):
    return {"t": "math", "v": None, "latex": s}


def run(*paras, choices=None):
    obj = {"stem": [{"inlines": list(p)} for p in paras],
           "choices": None if choices is None else [{"inlines": list(c)} for c in choices]}
    n = normalize_read(obj)
    flat = [[(i["t"], i["v"] if i["t"] == "text" else i["latex"]) for i in p["inlines"]] for p in obj["stem"]]
    return n, flat, obj


class RepairTest(unittest.TestCase):
    def test_restores_control_characters_in_latex(self):
        n, flat, _ = run([T("함수 "), M("\x0crac{1}{2}"), T("와 "), M("\text{x}"), T("의 값"),
                          M("a\x08eta"), M("\r" + "ight"), M("\n" + "eq")])
        self.assertEqual(n, 5)
        self.assertEqual([v for t, v in flat[0] if t == "math"],
                         ["\\frac{1}{2}", "\\text{x}", "a\\beta", "\\right", "\\neq"])

    def test_single_letter_variables_become_math(self):
        n, flat, _ = run([T("점 A 와 x 가 있다. ABC 는")])
        self.assertEqual(n, 1)
        self.assertEqual(flat[0], [("text", "점 "), ("math", "A"), ("text", " 와 "), ("math", "x"),
                                   ("text", " 가 있다. ABC 는")])

    def test_hangul_inside_math_moves_to_text(self):
        _, flat, _ = run([T("집합 "), M("x는 양수"), T("이다")])
        self.assertEqual(flat[0], [("text", "집합 "), ("math", "x"), ("text", "는 양수이다")])
        _, flat, _ = run([M("x+1 이면")])
        self.assertEqual(flat[0], [("math", "x+1"), ("text", " 이면")])

    def test_text_command_shell_and_unmatched_brackets(self):
        _, flat, _ = run([T("(나) "), M("\\text{개}")])
        self.assertEqual(flat[0], [("text", "(나) 개")])
        _, flat, _ = run([M("(가)")])
        self.assertEqual(flat[0], [("text", "(가)")])

    def test_paragraph_cut_at_line_end_is_joined(self):
        n, flat, _ = run([T("다음 중 옳은 것을")], [T("고르시오.")])
        self.assertEqual((n, flat), (1, [[("text", "다음 중 옳은 것을 고르시오.")]]))

    def test_paragraphs_that_must_stay_separate(self):
        _, flat, _ = run([T("다음 중 옳은 것은?")], [T("ㄱ. 보기")])
        self.assertEqual(len(flat), 2)
        _, flat, _ = run([T("문제 문장")], [T("(단, "), M("x"), T("는 양수)")])
        self.assertEqual(len(flat), 2)
        _, flat, _ = run([T("문제 문장")], [T("<보기>")], [T("ㄱ. 첫째")])
        self.assertEqual(len(flat), 3)
        _, flat, _ = run([T("앞 문장이 수식으로 끝난다 "), M("x+1")], [T("다음 문장")])
        self.assertEqual(len(flat), 2)

    def test_choices_are_fixed_and_none_is_ok(self):
        n, _, obj = run([T("문제")], choices=[[T("값은 "), M("\x0crac{1}{2}")]])
        self.assertEqual(n, 1)
        self.assertEqual(obj["choices"][0]["inlines"][1]["latex"], "\\frac{1}{2}")
        self.assertEqual(normalize_read({"stem": [], "choices": None}), 0)

    def test_clean_input_is_unchanged_and_second_pass_changes_nothing(self):
        n, _, _ = run([T("두 점 "), M("A(1,2)"), T("와 "), M("B(3,4)"), T("를 지나는 직선은?")])
        self.assertEqual(n, 0)
        obj = {"stem": [{"inlines": [T("점 x 와")]}], "choices": None}
        self.assertEqual(normalize_read(obj), 1)
        self.assertEqual(normalize_read(obj), 0)


if __name__ == "__main__":
    unittest.main()
