"""B5-2b-4: 열 분할 폴백 (설계 5.3). LLM이 실패했거나 칸이 0개일 때 쓴다.
세로 투영(열별 잉크 비율)에서 글자 없는 세로 골짜기로 열을 나누고, 열마다 큰 칸 1개를 만든다(번호는 None).
맨 위 안내문과 맨 아래 면 표시가 골짜기를 가리지 않도록 BAND 안의 줄만 본다(칸의 위·아래도 이 범위 안).
거칠게 나누는 것이 목적이다. 선생님이 네모를 직접 맞춘다."""
import numpy as np

from ..ports import SegmentDraft
from .segment_snap import ink_mask

BAND = (0.12, 0.92)    # 골짜기와 칸의 세로 범위를 찾는 구간(페이지 높이 대비)
GUTTER_MIN = 0.02      # 이 폭(페이지 너비 대비) 이상 비어야 열 사이로 본다
GUTTER_EMPTY = 0.01    # 이 비율 이하의 열은 '비었다'로 본다
ROW_INK = 0.002        # 이 비율 넘게 잉크가 있는 줄만 글줄로 본다
PAD = 0.005
MAX_COLUMNS = 3

FALLBACK_MESSAGE = "문제 칸을 자동으로 나누지 못했어요. 네모를 직접 맞춰 주세요."


def _whole():
    return [SegmentDraft(bbox=(0.0, 0.0, 1.0, 1.0), number=None)]


def detect_columns(gray) -> list:
    mask = ink_mask(gray)
    if mask is None:
        return _whole()
    H, W = mask.shape
    r0, r1 = int(BAND[0] * H), max(int(BAND[0] * H) + 1, int(BAND[1] * H))
    band = mask[r0:r1]
    cols = band.mean(axis=0)
    ink = np.flatnonzero(cols > GUTTER_EMPTY)
    if ink.size == 0:
        return _whole()
    lo, hi = int(ink[0]), int(ink[-1])
    empty = cols[lo:hi + 1] <= GUTTER_EMPTY
    gaps, i = [], 0
    while i < len(empty):
        if empty[i]:
            j = i
            while j + 1 < len(empty) and empty[j + 1]:
                j += 1
            if j - i + 1 >= GUTTER_MIN * W:
                gaps.append((lo + i, lo + j))
            i = j + 1
        else:
            i += 1
    gaps = sorted(sorted(gaps, key=lambda g: g[0] - g[1])[:MAX_COLUMNS - 1])   # 가장 넓은 골짜기만, 왼쪽부터
    spans, start = [], lo
    for a, b in gaps:
        spans.append((start, a - 1))
        start = b + 1
    spans.append((start, hi))
    out = []
    for s, e in spans:
        rows = np.flatnonzero(band[:, s:e + 1].mean(axis=1) > ROW_INK)
        if rows.size == 0:
            continue
        box = (max(0.0, s / W - PAD), max(0.0, (r0 + int(rows[0])) / H - PAD),
               min(1.0, (e + 1) / W + PAD), min(1.0, (r0 + int(rows[-1]) + 1) / H + PAD))
        out.append(SegmentDraft(bbox=tuple(round(v, 4) for v in box), number=None))
    return out or _whole()
