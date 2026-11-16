"""B5-2b-3: 가장자리 맞춤 (설계 5.2의 3번). 입력은 보정본의 회색조 배열(uint8, 높이x너비)과 SegmentDraft 목록.
- 먼저 위쪽에 여유(TOP_PAD)를 조금 더한다(E2에서 첫 줄이 잘린 칸이 있었음. 크기는 임시 값).
- 각 경계를 +-TOL 안에서 '글자가 없는 줄/열'(투영 프로파일이 거의 0)로 옮긴다.
  이미 여백이면 그대로 둔다. 글줄을 자르고 있으면 바깥쪽 여백을 먼저 찾아 글줄을 칸 안에 넣고,
  바깥에 없으면 안쪽 여백으로 간다. 여백이 없으면 그대로 둔다. 페이지 가장자리(0, 1)는 옮기지 않는다.
- 옮긴 뒤 겹친 칸은 segment_post와 같은 규칙으로 정리한다. 읽는 순서는 바꾸지 않는다.
이미지가 단색에 가깝거나 칸이 없으면 입력을 그대로 돌려준다. LLM·OpenCV 없이 numpy·Pillow만 쓴다."""
import numpy as np
from PIL import Image

from ..ports import SegmentDraft
from .segment_post import _resize, _resolve_overlaps

TOL = 0.03          # 경계를 옮길 수 있는 범위(페이지 높이·너비 대비)
TOP_PAD = 0.008     # 위쪽 여유(임시 값, 사진으로 확인 필요)
EMPTY = 0.004       # 이 값 이하면 '글자 없음'(칸 폭·높이 대비 잉크 비율)
MAX_SIDE = 1000     # 프로파일 계산용으로 줄이는 긴 변
MIN_SIZE = 0.01     # 맞춘 뒤 칸의 최소 폭·높이(비율)


def _otsu(gray: np.ndarray) -> int:
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    levels = np.arange(256)
    w0, s0 = np.cumsum(hist), np.cumsum(levels * hist)
    w1 = hist.sum() - w0
    ok = (w0 > 0) & (w1 > 0)
    m0 = s0 / np.where(w0 > 0, w0, 1)
    m1 = (s0[-1] - s0) / np.where(w1 > 0, w1, 1)
    return int(np.argmax(np.where(ok, w0 * w1 * (m0 - m1) ** 2, -1.0)))


def ink_mask(gray: np.ndarray):
    """잉크(True) 마스크. 긴 변을 MAX_SIDE로 줄이고, 거의 단색이면 None."""
    g = np.asarray(gray)
    if g.ndim != 2 or g.size == 0:
        return None
    g = g.astype(np.uint8)
    h, w = g.shape
    s = MAX_SIDE / max(h, w)
    if s < 1:
        g = np.asarray(Image.fromarray(g).resize((max(1, round(w * s)), max(1, round(h * s))), Image.BOX))
    if int(g.max()) - int(g.min()) < 40:
        return None
    return g <= min(_otsu(g), 200)   # Otsu 경계 t 이하를 잉크로(흑백뿐인 그림에서 t가 0이어도 잡힌다)


def _profile(mask, other_slice, axis):
    """axis=0: 줄(y)별 잉크 비율, axis=1: 열(x)별 잉크 비율. 약간 매끈하게 한다."""
    part = mask[:, other_slice] if axis == 0 else mask[other_slice, :]
    prof = part.mean(axis=1 if axis == 0 else 0)
    k = max(1, round(0.002 * len(prof)))
    return np.convolve(prof, np.ones(k) / k, mode="same") if k > 1 else prof


def _snap(profile, pos: int, tol_n: int, outward: int) -> int:
    n = len(profile)
    pos = min(max(pos, 0), n - 1)
    if profile[pos] <= EMPTY:
        return pos
    lo, hi = max(0, pos - tol_n), min(n - 1, pos + tol_n)
    up, down = range(pos + 1, hi + 1), range(pos - 1, lo - 1, -1)
    for rng in ((up, down) if outward > 0 else (down, up)):
        for i in rng:
            if profile[i] <= EMPTY:
                return i
    return pos


def _sl(a, b, n):
    lo = min(int(a * n), n - 1)
    return slice(lo, max(lo + 1, min(n, int(np.ceil(b * n)))))


def snap_segments(gray, drafts: list, *, tol: float = TOL, top_pad: float = TOP_PAD) -> list:
    mask = ink_mask(gray) if drafts else None
    if mask is None:
        return list(drafts)
    H, W = mask.shape
    items = [{"number": d.number, "box": tuple(d.bbox), "choices": d.choices_bbox, "figure": d.figure_bbox}
             for d in drafts]
    for it in items:
        x0, y0, x1, y1 = it["box"]
        ny0 = max(0.0, y0 - top_pad)
        py = _profile(mask, _sl(x0, x1, W), 0)
        ty = max(1, round(tol * H))
        if ny0 > 0:
            ny0 = _snap(py, round(ny0 * H), ty, -1) / H
        ny1 = y1
        if y1 < 1:
            ny1 = _snap(py, round(y1 * H), ty, +1) / H
        px = _profile(mask, _sl(ny0, ny1, H), 1)
        tx = max(1, round(tol * W))
        nx0, nx1 = x0, x1
        if x0 > 0:
            nx0 = _snap(px, round(x0 * W), tx, -1) / W
        if x1 < 1:
            nx1 = _snap(px, round(x1 * W), tx, +1) / W
        if nx1 - nx0 >= MIN_SIZE and ny1 - ny0 >= MIN_SIZE:
            _resize(it, (nx0, ny0, nx1, ny1))
    items = _resolve_overlaps(items)

    def r(b):
        return None if b is None else tuple(round(v, 4) for v in b)

    return [SegmentDraft(bbox=r(it["box"]), number=it["number"], choices_bbox=r(it["choices"]),
                         figure_bbox=r(it["figure"])) for it in items]
