"""rm/it 기준(1단계) 테스트. 공백은 무시하고 비교한다."""
import re

import pytest

from app.export.math.convert import convert


def _n(s):
    return re.sub(r"\s+", "", s)


CASES = [
    (r"\triangle ABC", "rm TRIANGLE A B C"),            # 대문자 → rm (끝이면 it 생략)
    (r"\angle A = 30^\circ", "rm angle A it = 30°"),    # rm 뒤에는 it로 되돌림
    (r"\overline{AB}", "bar {rm A B}"),
    (r"x+y", "x+y"),                                     # 소문자 변수는 it
    (r"6cm", "6 rm c m"),                                # 숫자 뒤 단위는 rm
    (r"3cm+x", "3 rm c m it + x"),
    (r"F(x)", "F (x)"),                                  # 함수 이름은 it
    (r"A^{c}", "A ^{c}"),                                # 첨자 기반은 it
    (r"\mathrm{AB}+x", "rm A B it + x"),                # 이미 rm이면 그대로
    # 2단계: 합동·프라임
    (r"\triangle ABE \equiv \triangle BCF", "rm TRIANGLE A B E EQUIV TRIANGLE B C F"),
    (r"B'", "rm B prime"),
    (r"B^{\prime}", "rm B prime"),
    (r"A'B'C'", "rm A prime B prime C prime"),
    (r"B'C = 3", "rm B prime C it = 3"),
    (r"F'(x)", "F prime (x)"),                          # 도함수 F'(x)는 it
    (r"x'", "x prime"),
    # 3단계: 닮음·합동
    (r"\triangle ABC \sim \triangle DEF", "rm TRIANGLE A B C SIM TRIANGLE D E F"),
    (r"\triangle ABC \cong \triangle DEF", "rm TRIANGLE A B C CONG TRIANGLE D E F"),
]


@pytest.mark.parametrize("latex,expected", CASES)
def test_roman_rule(latex, expected):
    r = convert(latex)
    assert r.ok, r.error
    assert _n(r.script) == _n(expected)
