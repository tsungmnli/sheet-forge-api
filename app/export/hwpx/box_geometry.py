"""<보기> 상자의 크기·위치 계산. XML 없이 숫자만 다뤄서 한글 없이도 테스트할 수 있다.

기준은 샘플 시험지(시험지.hwpx)의 묶음 개체(본문 글상자 + 제목 글상자):
  - 상자 폭 25585 = 2단 한 단 폭(25795) - 210
  - 제목 글상자 5124 x 1865 = 글자 크기 1000 기준 (글자 4.3em + 안쪽 여백 566 + 258) x (글자 + 566 + 299)
  - 본문 글상자는 제목 높이의 절반(932)만큼 아래로 내리고, 제목 글상자의 가운데가 본문 윗선에 오게 한다
  - 본문 높이 8504 ≈ 글줄 합 6480 + 위아래 여유 2 x 1032 (여유 = 제목 높이의 절반 + 100)
높이는 한글이 다시 계산해 주지 않으므로(고정값) 줄 수에서 추정한다. 추정값이라는 점은 호출한 쪽이 보고한다.
"""
import math
from dataclasses import dataclass

BOX_WIDTH_TRIM = 210        # 상자 폭 = 단 폭 - 이 값 (샘플 25795 → 25585)
DEFAULT_COL_W = 25795       # layout이 없을 때(테스트) 쓰는 단 폭
TEXT_MARGIN = 283           # drawText textMargin (샘플)
TITLE_TEXT_PAD = 258        # 제목 글자 폭에 더하는 여유 (샘플에서 5124가 되게 맞춘 값)
TITLE_H_PAD = 299           # 제목 높이 = 글자 + 안쪽 여백 2 x 283 + 이 값 (샘플 1865)
TITLE_GAP = 100             # 제목 아래쪽과 첫 글줄 사이 최소 간격
V_PAD_MIN = 300             # 제목이 작아도 확보하는 위아래 여유
EQ_LINE_RATIO = 1.17        # 수식이 든 줄의 줄 높이 / 글자 크기 (샘플 1170 / 1000)
EQ_OUT_MARGIN = 112         # 수식 하나의 좌우 바깥 여백 합 (hp:outMargin 56 x 2)

# 글자 폭 계수(em). builders.py의 선택지 폭 추정과 같은 값이다.
CH_HANGUL, CH_ASCII, CH_SPACE = 1.0, 0.55, 0.4


def text_em(s: str) -> float:
    return sum(CH_SPACE if c == " " else CH_ASCII if c.isascii() else CH_HANGUL for c in s)


def display_title(title: str) -> str:
    """'<보기>'는 샘플처럼 '< 보 기 >'로 벌려 쓴다. 다른 제목은 그대로."""
    return "< 보 기 >" if "".join(title.split()) in ("<보기>", "〈보기〉") else title


@dataclass(frozen=True)
class BoxGeometry:
    width: int       # 묶음 개체 전체 폭 = 본문 글상자 폭
    height: int      # 묶음 개체 전체 높이 = title_h // 2 + body_h
    body_y: int      # 본문 글상자의 위쪽 위치(= title_h // 2)
    body_h: int
    title_w: int
    title_h: int
    title_x: int     # 제목 글상자의 가로 위치 (가로 가운데)


def box_width(col_w: float) -> int:
    return int(col_w) - BOX_WIDTH_TRIM


def title_size(title: str, font: int) -> tuple:
    w = round(text_em(title) * font) + 2 * TEXT_MARGIN + TITLE_TEXT_PAD
    h = font + 2 * TEXT_MARGIN + TITLE_H_PAD
    return w, h


def line_rows(width_em: float, n_eq: int, text_w: float, font: int) -> int:
    """한 문단이 상자 안에서 차지할 줄 수(자동 줄바꿈 추정)."""
    px = width_em * font + n_eq * EQ_OUT_MARGIN
    return max(1, math.ceil(px / text_w)) if text_w > 0 else 1


def body_content_height(lines: list, font: int, line_spacing_pct: int) -> int:
    """lines: [(줄 수, 수식 포함 여부), ...] → 글줄을 모두 쌓은 높이(마지막 줄 뒤 간격 제외)."""
    spacing = round(font * (line_spacing_pct - 100) / 100)
    total, h = 0, 0
    for rows, has_eq in lines:
        lh = round(font * EQ_LINE_RATIO) if has_eq else font
        h += rows * lh
        total += rows
    return h + max(0, total - 1) * spacing


# ---------------------------------------------------------------- 표 [샘플 시험지.hwpx 기준]
TABLE_SIDE_TRIM = 1134      # 표 폭 = 단 폭 - 이 값 (샘플 24661 = 25795 - 1134)
CELL_MARGIN_X = 510         # 셀 안쪽 좌우 여백 (샘플 cellMargin)
CELL_MARGIN_Y = 141         # 셀 안쪽 위아래 여백
MIN_ROW_RATIO = 1.85        # 최소 행 높이 / 글자 크기 (샘플 1850 / 1000)
ROW_PAD = 288               # 글줄 높이 + 위아래 여백(282) 위에 더하는 여유
MIN_COL_EM = 2.0            # 열 폭을 나눌 때 한 열의 최소 가중치(em)


def table_width(col_w: float) -> int:
    return int(col_w) - TABLE_SIDE_TRIM


def split_widths(weights: list, total: int) -> list:
    """열 가중치에 비례해 total을 나눈다. 합은 정확히 total, 마지막 열이 반올림 오차를 흡수한다."""
    w = [max(MIN_COL_EM, x) for x in weights]
    s = sum(w)
    out = [round(total * x / s) for x in w]
    out[-1] += total - sum(out)
    return out


def row_height(cells: list, col_widths: list, font: int, line_spacing_pct: int) -> int:
    """cells: [(글자 폭 em, 수식 수, 수식 포함 여부), ...] 한 행의 높이. 한글은 행을 내용에 맞춰 늘리므로 최소값 역할."""
    best = 0
    for (em, n_eq, has_eq), cw in zip(cells, col_widths):
        rows = line_rows(em, n_eq, cw - 2 * CELL_MARGIN_X, font)
        best = max(best, body_content_height([(rows, has_eq)], font, line_spacing_pct))
    return max(round(MIN_ROW_RATIO * font), best + 2 * CELL_MARGIN_Y + ROW_PAD)


def plan_box(col_w: float, title: str, line_rows_eq: list, font: int, line_spacing_pct: int) -> BoxGeometry:
    """col_w: 이 상자가 들어갈 단의 폭. line_rows_eq: [(줄 수, 수식 포함 여부), ...]."""
    width = box_width(col_w)
    tw, th = title_size(display_title(title), font)
    tw = min(tw, width)
    content = body_content_height(line_rows_eq, font, line_spacing_pct)
    inset = max(th // 2 + TITLE_GAP, TEXT_MARGIN + V_PAD_MIN)
    body_h = content + 2 * inset
    return BoxGeometry(width=width, height=th // 2 + body_h, body_y=th // 2, body_h=body_h,
                       title_w=tw, title_h=th, title_x=(width - tw) // 2)
