"""math 패키지 골든 테스트: README 4.3 / 4.3.1 표 (공백은 렌더링에 영향이 없으므로 무시하고 비교)."""
import re

import pytest

from app.export.math.convert import convert

GOLDEN = [
    (r"x^2", "x ^{2}"),
    (r"\frac{3x+1}{x+1}", "{3x+1} over {x+1}"),
    (r"-\frac{2}{x}", "- {2} over {x}"),
    (r"\sqrt{2x+a}", "sqrt {2x+a}"),
    (r"h \circ g", "h CIRC g"),
    (r"f^{-1}(4)", "f ^{-1} (4)"),
    (r"x^2+y^2+6x-20y+1=0", "x ^{2} +y ^{2} +6x-20y+1=0"),
    (r"(x+3)^2+(y-10)^2=108", "(x+3) ^{2} +(y-10) ^{2} =108"),
    (r"\sqrt[3]{x}", "root {3} of {x}"),
    (r"{}_nC_r", "{} _{n} C _{r}"),
    (r"\sin^2 x", "sin ^{2} `x"),
    (r"\min(a,b)", "min(a,`b)"),
    (r"30^\circ", "30°"),
    (r"\left(\frac{a}{b}\right)", "LEFT ( {a} over {b} RIGHT )"),
    (r"\{\frac{a}{b}\}", "LEFT lbrace {a} over {b} RIGHT rbrace"),
    (r"\{1,2\}", "lbrace 1,`2 rbrace"),
    (r"3\mathrm{km}+x", "3 rm km it + x"),     # 뒤에 내용이 있으면 it으로 되돌린다(v2 V03)
    (r"3\mathrm{km}", "3 rm km"),               # 맨 끝이면 it 불필요(v2 V05·V06)
    (r"x\in\mathbb{R}", "x IN rm R"),
    (r"\sum_{i=1}^{n}a_i", "sum _{i=1} ^{n} a _{i}"),
    (r"\lim_{x\to 0}f(x)", "lim _{x ->0} f (x)"),
    (r"\begin{cases}a\\b\end{cases}", "cases{a # b}"),
    (r"x \in A", "x IN A"),
    (r"|x|", "|x|"),
    (r"A^{c}", "A ^{c}"),
    (r"a \le b", "a LEQ b"),
    (r"a \ne b", "a != b"),
    (r"\overline{AB}", "bar {AB}"),
    (r"\dot{6}", "dot {6}"),
]


def _n(s):
    return re.sub(r"\s+", "", s)


@pytest.mark.parametrize("latex,expected", GOLDEN)
def test_golden(latex, expected):
    r = convert(latex)
    assert r.ok, r.error
    assert _n(r.script) == _n(expected)


def test_variables_are_separated():
    # 연속 영문자는 예약어로 합쳐지므로(xin → ξn) 글자마다 분리해야 한다.
    assert "x i n" in convert("xin").script


def test_tokens_are_not_glued():
    # '-'와 '>'를 붙이면 화살표(->)가 되므로 공백으로 분리해야 한다.
    assert "- >" in convert("a->b").script


def test_documented_vocab_is_gated():
    r = convert(r"\exists x")
    assert not r.ok and "exists" in r.error and r.error_pos == 0
    assert convert(r"\exists x", allow_documented=True).ok


def test_unknown_command_reports_position():
    r = convert(r"x+\foo")
    assert not r.ok and r.error_pos == 2


def test_empty_is_error():
    assert not convert("  ").ok


def test_text_keeps_spaces_and_warns():
    r = convert(r"\text{x 의 값}")
    assert r.ok and '"x 의 값"' in r.script
    assert any(w.startswith("TEXT_IN_MATH") for w in r.warnings)


def test_long_number_is_quoted():
    assert '"1234567890"' in convert("1234567890").script


def test_degree_symbol_from_unicode():
    assert _n(convert("30°").script) == "30°"


def test_width_estimate_is_monotonic():
    a, b = convert("x+y"), convert("x+y+z")
    assert 0 < a.est_width_em < b.est_width_em


# ---------------------------------------------------------------- 갤러리 코퍼스(v1·v2) 골든
# tests/fixtures/math_gallery_v1_results.json, math_gallery_v2_results.json 이 있어야 돈다(없으면 건너뜀).
# 같은 LaTeX를 여러 표기(a/b/c)로 실험한 항목이 있으므로, "우리 출력이 그 LaTeX의 검증된(ok) 표기 중 하나"인지 본다.
# 공백·얇은 공백(`)·~는 렌더링에 영향이 없으므로 비교에서 뺀다.
import json
from collections import defaultdict
from pathlib import Path

_FIX = Path(__file__).resolve().parent.parent / "fixtures"
# 검증된 표기는 작은 괄호·절댓값이지만, 변환기는 분수를 감싼 괄호를 LEFT/RIGHT로 승격한다(6.7 방출 정책).
_PROMOTED = {r"(\frac{a}{b})", r"|\frac{a}{b}|"}


def _nz(s):
    return re.sub(r"[\s`~]+", "", s)


def _groups():
    g = defaultdict(lambda: {"ok": set(), "bad": set()})
    for name in ("math_gallery_v1_results.json", "math_gallery_v2_results.json"):
        path = _FIX / name
        if not path.exists():
            continue
        for x in json.loads(path.read_text(encoding="utf-8")):
            g[x["latex"]]["ok" if x["verdict"] == "ok" else "bad"].add(_nz(x["script"]))
    return [(k, v["ok"], v["bad"]) for k, v in g.items() if v["ok"]]


@pytest.mark.parametrize("latex,ok_set,bad_set", _groups())
def test_corpus(latex, ok_set, bad_set):
    r = convert(latex, allow_documented=True)
    assert r.ok, r.error
    s = _nz(r.script)
    if latex in _PROMOTED:
        assert s.startswith("LEFT")
        return
    # 대부분의 명령은 대소문자 양쪽이 동작한다(4.3.1: in/IN). 함수명만 소문자 전용이라 무효 표기는 대소문자를 구분해 본다.
    assert s.lower() in {t.lower() for t in ok_set}
    if not latex.isalpha():          # 'xin'은 공백 제거 후 무효 표기와 같아지므로(변수 분리 규칙) 따로 검증한다
        assert s not in bad_set
