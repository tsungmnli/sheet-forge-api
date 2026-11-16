"""수식 `#` 줄바꿈 계획 테스트 (README 4.6, 설계 10장)."""
import re

from app.export.math.convert import convert
from app.export.math.parser import Ctx, parse
from app.export.math.wrap import break_candidates, plan_wrap

from tests.export.test_math import GOLDEN

LONG = r"x^2+y^2+6x-20y+1=0"


def nz(s):
    """공백과 `#`을 지워 비교한다(줄바꿈은 렌더링 내용을 바꾸지 않는다)."""
    return re.sub(r"[\s#]+", "", s)


def nodes(latex):
    return parse(latex, Ctx())


def test_candidates_are_top_level_binary_ops():
    assert len(break_candidates(nodes(LONG))) == 5          # + + - + =
    assert len(break_candidates(nodes(r"-x+1"))) == 1        # 맨 앞 부호는 제외
    assert len(break_candidates(nodes(r"f(x)=-1"))) == 1     # =만 (뒤의 -는 부호)
    assert len(break_candidates(nodes(r"(a+b)^2"))) == 0     # 괄호 안은 최상위가 아님
    assert len(break_candidates(nodes(r"\frac{a+b}{c-d}"))) == 0
    assert len(break_candidates(nodes(r"\sin -x"))) == 0     # 함수명 바로 뒤


def test_no_break_when_it_fits():
    r = convert(LONG, max_width_em=50)
    assert "#" not in r.script and not r.breaks and not r.auto_broken and not r.too_wide
    assert r.script == convert(LONG).script


def test_default_call_is_unchanged():
    r = convert(LONG)
    assert r.breaks == [] and not r.auto_broken and not r.too_wide
    assert r.line_widths_em == [r.est_width_em]


def test_greedy_lines_fit_and_est_width_unchanged():
    base = convert(LONG)
    r = convert(LONG, max_width_em=6.0)
    assert r.auto_broken and r.breaks and not r.too_wide
    assert all(w <= 6.0 for w in r.line_widths_em)
    assert len(r.line_widths_em) == len(r.breaks) + 1
    assert r.est_width_em == base.est_width_em
    assert abs(sum(r.line_widths_em) - base.est_width_em) < 0.01   # 줄 폭의 합 = 전체 폭


def test_greedy_takes_rightmost_fitting_candidate():
    p = plan_wrap(nodes(LONG), 6.0)
    first_line = p.line_widths[0]
    assert first_line <= 6.0
    # 다음 후보까지 포함하면 넘는다 = 오른쪽에서 가장 가까운 곳에서 끊었다
    cands = break_candidates(nodes(LONG))
    nxt = [c for c in cands if c > p.cuts[0]][0]
    from app.export.math.emit import node_widths
    assert sum(node_widths(nodes(LONG))[:nxt]) > 6.0


def test_too_wide_without_break_points():
    r = convert(r"\frac{aaaaaaaaaaaaaaaaaaaaaa+bbbbbbbbbbbbbbbbbbbbbbbb}{c}", max_width_em=3.0)
    assert r.ok and r.too_wide and not r.breaks and "#" not in r.script


def test_too_wide_when_a_segment_alone_is_too_long():
    r = convert(r"1234567890123456789012345+1", max_width_em=5.0)   # 첫 조각이 이미 넘음
    assert r.too_wide


def test_user_breaks_override_auto():
    r = convert(r"a+b+c", max_width_em=100, breaks=[1])
    assert r.script.count("#") == 1 and r.breaks == [1] and not r.auto_broken
    assert nz(r.script) == nz(convert(r"a+b+c").script)
    assert r.script.index("#") > r.script.index("+")          # 두 번째 + 앞


def test_user_empty_list_suppresses_auto_break():
    r = convert(LONG, max_width_em=3.0, breaks=[])
    assert "#" not in r.script and r.too_wide


def test_user_break_out_of_range_is_ignored_with_warning():
    r = convert(r"a+b", breaks=[0, 7, -1])
    assert r.breaks == [0] and r.ignored_breaks == [7, -1]
    assert any(w.startswith("BREAK_IGNORED") for w in r.warnings)


def test_wrapping_never_changes_content_over_corpus():
    """# 을 지우면(그리고 공백을 무시하면) 줄바꿈 없는 방출과 같다 — GOLDEN 전체, 아주 좁은 폭으로."""
    for latex, _ in GOLDEN:
        plain = convert(latex)
        if not plain.ok:
            continue
        wrapped = convert(latex, max_width_em=1.5)
        assert wrapped.ok
        assert nz(wrapped.script) == nz(plain.script), latex
        assert wrapped.script.count("#") >= plain.script.count("#")


def test_failure_still_returns_error_with_wrap_args():
    r = convert(r"\foo", max_width_em=5)
    assert not r.ok and r.error is not None
