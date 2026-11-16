"""스모크 hwpx 생성(M1 텍스트, M2 수식). 사용자가 한글에서 열어 확인한다(설계 14장 5).
사용: python scripts/make_smoke.py OUT_DIR"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.export.hwpx import ExportMeta, ExportRequest, export_hwpx  # noqa: E402

META = ExportMeta("M1 스모크", "2026-11-15T00:00:00Z")


def problem(i, long=False):
    base = [("세 함수 f, g, h에 대하여 f(x)=5x-1, g(x)=x+3일 때 합성함수의 값을 구하시오. ", 1)]
    if long:  # 한 단을 넘길 수 있는 긴 문항(keep 확인용)
        base = [(f"{i}번 문항의 {k + 1}번째 문단입니다. 이 문장은 좁은 단에서 줄바꿈이 일어나도록 충분히 길게 씁니다. "
                 "문항이 단 경계에서 쪼개지지 않고 통째로 다음 단으로 넘어가는지 확인합니다.", 1) for k in range(3)]
    return {"id": f"p{i}", "status": "confirmed",
            "content": {"stem": [{"type": "paragraph", "inlines": [{"t": "text", "v": t}]} for t, _ in base]}}


CASES = {
    "m1_1col_text.hwpx": ({}, 12, False),
    "m1_2col_keep.hwpx": ({"columns": {"count": 2}}, 40, True),
    "m1_3col_keep.hwpx": ({"columns": {"count": 3}}, 40, True),
    "m1_font_spacing.hwpx": ({"typography": {"font_name": "맑은 고딕", "font_size_pt": 12, "line_spacing_pct": 130}},
                             12, False),
}

# ---------------------------------------------------------------- M2 수식
T = lambda v: {"t": "text", "v": v}
M = lambda latex, **kw: {"t": "math", "latex": latex, **kw}


def eq_problem(i, *inlines, pid=None):
    return {"id": pid or f"p{i}", "status": "confirmed",
            "content": {"stem": [{"type": "paragraph", "inlines": list(inlines)}]}}


def chain(n):  # a_1+a_2+…+a_n : 폭이 n에 비례해 늘어나는 탐침(단 가장자리 근처 동작 확인)
    return "+".join(f"a_{k}" for k in range(1, n + 1))


def m2_basic():
    P = [
        eq_problem(1, T("세 함수 "), M("f"), T(", "), M("g"), T(", "), M("h"), T("에 대하여 "), M("f(x)=5x-1"), T(", "),
                   M("g(x)=x+3"), T("일 때, "), M(r"(h \circ g \circ f)(1)"), T("의 값을 구하시오.")),
        eq_problem(2, T("함수 "), M(r"y=\frac{3x+1}{x+1}"), T("의 그래프가 점 "), M("A(1,2)"), T("를 지날 때 "), M("a"),
                   T("의 값은?")),
        eq_problem(3, M(r"\sqrt{2x+a}"), T("와 "), M(r"\sqrt[3]{x}"), T(", "), M(r"x^2+y^2+6x-20y+1=0")),
        eq_problem(4, T("극한 "), M(r"\lim_{x\to 0}\frac{\sin x}{x}"), T("과 합 "), M(r"\sum_{k=1}^{n}k^2"),
                   T("을 구하시오.")),
        eq_problem(5, T("집합 "), M(r"A=\{1,2,3\}"), T(", "), M(r"B=\{2,3,4\}"), T("일 때 "),
                   M(r"A\cup B")),
        eq_problem(6, T("길이가 "), M(r"3\mathrm{km}+x"), T("이고 각 "), M(r"30^\circ"), T("일 때 "), M(r"\angle ABC"),
                   T("의 값은?")),
        eq_problem(7, T("수식 안의 한글: "), M(r"\text{속력}=\frac{\text{거리}}{\text{시간}}")),
        eq_problem(8, T("변환할 수 없는 수식(폴백 확인): "), M(r"a\approx b")),
    ]
    return P


def m2_wrap():
    P = [
        eq_problem(1, T("짧은 수식은 줄바꿈 없이: "), M("x^2+1=0")),
        eq_problem(2, T("한 번 줄바꿈: "), M(r"x^2+y^2+6x-20y+1=0")),
        eq_problem(3, T("두 번 줄바꿈: "), M(r"x^2+y^2+6x-20y+1=3x^2-4y^2+5x-6y+7=0")),
        eq_problem(4, T("수식만 있는 문단 아래:")),
        eq_problem(5, M(r"(x+3)^2+(y-10)^2=108")),
        eq_problem(6, T("분수·루트 안은 끊지 않음(넘치면 경고): "),
                   M(r"\frac{aaaaaaaaaaaaaaaaaaaa+bbbbbbbbbbbbbbbbbbbbbbbb}{c}")),
        eq_problem(7, T("사용자 지정 위치(두 번째 + 앞): "), M(r"a+b+c+d", breaks=[1])),
    ]
    # 폭 탐침: n=3..9. 각 줄이 단 안에 들어오는지, 가장자리에 얼마나 가까운지 본다.
    P += [eq_problem(10 + n, T(f"탐침 n={n}: "), M(chain(n))) for n in range(3, 10)]
    return P


M2_CASES = {
    # 1단 10pt: 수식이 글자와 섞여 정상 표시되는지, sz=0 자동 계산(t6a)
    "m2_1col_eq.hwpx": ({}, m2_basic),
    # 3단, 단 폭 13417(t8·t10과 같은 조건: 좌우 30mm) — `#` 줄바꿈과 왼쪽 정렬
    "m2_3col_wrap.hwpx": ({"columns": {"count": 3}, "margins_mm": {"left": 30, "right": 30}}, m2_wrap),
    # 12pt: baseUnit 1200이 본문 크기와 맞는지(t17a)
    "m2_12pt_eq.hwpx": ({"typography": {"font_size_pt": 12}}, m2_basic),
}


# ---------------------------------------------------------------- M3 선택지
def ch(*texts):
    return [[T(t)] for t in texts]


def choice_problem(i, stem, items):
    q = eq_problem(i, T(stem))
    q["content"]["choices"] = {"items": items, "layout": "auto"}
    return q


def m3_choices():
    return [
        choice_problem(1, "짧은 숫자 선택지(5열 한 줄 예상):", ch("1", "3", "5", "7", "9")),
        choice_problem(2, "두 자리 수:", ch("12", "24", "36", "48", "60")),
        choice_problem(3, "수식 선택지:", [[M(r"\frac{1}{2}")], [M(r"\sqrt{3}")], [M("x^2+1")], [M("2x-1")], [M(r"\frac{3x+1}{x+1}")]]),
        choice_problem(4, "중간 길이 글(3+2 예상):", ch("함수 f는 증가한다", "함수 g는 감소한다", "f와 g는 같다", "알 수 없다", "모두 옳다")),
        choice_problem(5, "긴 글(1열 예상):", ch("가나다라마바사아자차카타파하" * 3, "가나다라마바사아자차카타파하" * 3,
                                             "가나다라마바사아자차카타파하" * 3, "가나다라마바사아자차카타파하" * 3, "가나다라마바사아자차카타파하" * 3)),
        choice_problem(6, "선택지 4개:", ch("1", "2", "3", "4")),
    ]


M3_CASES = {
    "m3_1col_choices.hwpx": ({}, m3_choices),
    "m3_2col_choices.hwpx": ({"columns": {"count": 2}}, m3_choices),
    "m3_3col_choices.hwpx": ({"columns": {"count": 3}, "margins_mm": {"left": 30, "right": 30}}, m3_choices),
}
M2_CASES.update(M3_CASES)

# ---------------------------------------------------------------- M4 그림
import struct, zlib  # noqa: E402
from app.export.hwpx.images import ImageData  # noqa: E402


def make_png(w, h):
    """한글에서 방향·비율을 알아보도록 왼쪽 위 빨간 사각형 + 검은 테두리가 있는 PNG(표준 라이브러리만 사용)."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rows = bytearray()
    for y in range(h):
        rows.append(0)
        for x in range(w):
            edge = x < 3 or y < 3 or x >= w - 3 or y >= h - 3
            mark = x < w // 5 and y < h // 5
            rows += bytes((255, 0, 0) if mark else (0, 0, 0) if edge else (225, 235, 250))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b""))


M4_IMAGES = {"wide": ImageData(make_png(400, 300), 400, 300), "square": ImageData(make_png(200, 200), 200, 200),
             "tall": ImageData(make_png(150, 300), 150, 300)}


def fg(ref, placement="after_stem", **kw):
    return {"id": "f_" + ref, "clean_ref": ref, "use": "clean", "placement": placement, **kw}


def fig_problem(i, stem, figures, items=None):
    q = eq_problem(i, T(stem))
    q["content"]["figures"] = figures
    if items:
        q["content"]["choices"] = {"items": items, "layout": "auto"}
    return q


def m4_figures():
    return [
        fig_problem(1, "폭 45mm 그림(stem 아래):", [fg("wide", width_mm=45)]),
        fig_problem(2, "그림 + 선택지(그림이 선택지 앞):", [fg("square", width_mm=30)], ch("1", "2", "3", "4", "5")),
        fig_problem(3, "그림이 선택지 뒤:", [fg("square", "after_choices", width_mm=30)], ch("1", "2", "3", "4", "5")),
        fig_problem(4, "폭 미지정(400×300px → 30000, 좁은 단에서는 축소):", [fg("wide")]),
        fig_problem(5, "단 폭보다 큰 그림(200mm → 축소 확인):", [fg("wide", width_mm=200)]),
        fig_problem(6, "그림 두 개:", [fg("square", width_mm=25), fg("tall", width_mm=25)]),
        fig_problem(7, "없는 그림 → 이 문항은 제외되고 다음 번호가 이어져야 함:", [fg("nope")]),
        fig_problem(8, "마지막 문항(번호가 07이어야 함):", [fg("tall", width_mm=20)]),
    ]


M4_CASES = {
    "m4_1col_figs.hwpx": {},
    "m4_2col_figs.hwpx": {"columns": {"count": 2}},
    "m4_3col_figs.hwpx": {"columns": {"count": 3}, "margins_mm": {"left": 30, "right": 30}},
}

# ---------------------------------------------------------------- M5 쪽 설정·서식 (텍스트·수식·선택지·그림 혼합)
def m5_mixed():
    P = m2_basic()[:3] + m3_choices()[2:5] + m4_figures()[:3] + [m4_figures()[5]]
    for k, q in enumerate(P):
        q["id"] = f"m{k}"
    return P


M5_CASES = {
    # 가로 + 2단: 본문 폭 = 긴 변 기준(t18)
    "m5_landscape_2col.hwpx": {"orientation": "landscape", "columns": {"count": 2}},
    # B5 + 3단 + 제본 10mm + 좌우 12/14mm (t16)
    "m5_b5_3col_gutter.hwpx": {"paper": {"kind": "B5", "width_mm": 182, "height_mm": 257}, "columns": {"count": 3},
                               "margins_mm": {"left": 12, "right": 14, "gutter": 10}},
    # 글꼴·크기·줄 간격: 수식 baseUnit이 14pt와 맞는지, 선택지 열 수가 달라지는지(t17)
    "m5_font14_spacing200.hwpx": {"typography": {"font_name": "맑은 고딕", "font_size_pt": 14, "line_spacing_pct": 200}},
    # 번호 서식 "{n}." 시작 5, 2단 양쪽 정렬
    "m5_numbering_justify.hwpx": {"columns": {"count": 2}, "typography": {"align": "justify"},
                                  "numbering": {"format": "{n}.", "start": 5}},
}

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "smoke")
    out.mkdir(parents=True, exist_ok=True)
    for name, (preset, n, long) in CASES.items():
        r = export_hwpx(ExportRequest([problem(i, long) for i in range(1, n + 1)], preset, META))
        (out / name).write_bytes(r.hwpx_bytes)
        print(name, len(r.hwpx_bytes), r.report.status, r.layout)
    for name, (preset, build) in M2_CASES.items():
        r = export_hwpx(ExportRequest(build(), preset, ExportMeta("M2 스모크", "2026-11-15T00:00:00Z")))
        (out / name).write_bytes(r.hwpx_bytes)
        print(name, len(r.hwpx_bytes), r.report.status, r.layout,
              {k: r.report.stats[k] for k in ("equations", "equations_wrapped", "choice_rows")})
        for it in r.report.items:
            if it.code in ("EQ_AUTO_BROKEN", "EQ_TOO_WIDE", "UNSUPPORTED_MATH", "MATH_NOTE", "CHOICES_NEAR_LIMIT"):
                print(f"   {it.code:<17} {it.problem_id} {it.where}: {it.message}")
    for name, preset in M4_CASES.items():
        r = export_hwpx(ExportRequest(m4_figures(), preset, ExportMeta("M4 스모크", "2026-11-15T00:00:00Z"), M4_IMAGES.get))
        (out / name).write_bytes(r.hwpx_bytes)
        print(name, len(r.hwpx_bytes), r.report.status, r.layout, {k: r.report.stats[k] for k in ("problems", "figures")})
        for it in r.report.items:
            if it.code.startswith("FIGURE_") or it.code == "CHOICES_NEAR_LIMIT":
                print(f"   {it.code:<17} {it.problem_id} {it.where}: {it.message}")
    for name, preset in M5_CASES.items():
        r = export_hwpx(ExportRequest(m5_mixed(), preset, ExportMeta("M5 스모크", "2026-11-15T00:00:00Z"), M4_IMAGES.get))
        (out / name).write_bytes(r.hwpx_bytes)
        print(name, len(r.hwpx_bytes), r.report.status, r.layout)
        for it in r.report.items:
            if it.code in ("EQ_AUTO_BROKEN", "EQ_TOO_WIDE", "CHOICES_NEAR_LIMIT") or it.code.startswith("FIGURE_"):
                print(f"   {it.code:<17} {it.problem_id} {it.where}: {it.message}")
