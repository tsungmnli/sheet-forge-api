"""④ 그림 정리(작업자 전용, LLM 없음). 설계 7장.

조명 평탄화 → 색 필기 제거(채도 높은 픽셀을 흰색으로) → 진한 픽셀만 남기고 작은 덩어리 제거(세기 1~4, 안티앨리어싱은 유지).
잉크가 정리 전의 40% 미만으로 줄면 과제거로 보고 정리본을 버린다(CleanResult.clean=None, 원본 그림을 쓴다).
검정·연필 필기는 색으로 못 지운다(알려진 한계, 선 굵기 필터는 E4에서 시험).
"""
import io

import cv2
import numpy as np
from PIL import Image

from ..ports import CleanResult
from .correct import flatten_lighting
from .decode import decode_image

SAT_MIN = 80            # HSV 채도(0~255)가 이 이상이면 색 필기로 본다
VAL_MIN = 40            # 너무 어두운 픽셀은 검정 선이므로 색으로 보지 않는다
MIN_KEEP_RATIO = 0.40   # 정리 후 잉크가 이 비율 미만이면 과제거
MIN_INK_PIXELS = 20     # 정리 전 잉크가 이보다 적으면 비교할 수 없어 정리를 포기한다
HUE_TOL = 12            # 색상(OpenCV 0~179, 원형)이 고른 색에서 ±이만큼이면 같은 색으로 본다
PALETTE_MAX = 5         # 색 견본 최대 개수
PALETTE_MIN_RATIO = 0.0008   # 그림 전체 픽셀 중 이 비율 미만인 색은 견본으로 내지 않는다(종이 얼룩·가장자리)
PALETTE_GRAY_MAX = 190       # 이보다 밝은 색(종이 색, 연한 음영)은 필기·인쇄 선이 아니므로 견본에서 뺀다


LEVELS = {            # level: (어두움 기준 T, 지울 덩어리 최대 크기 min_area, 1000px 폭 기준)
    1: (170, 15),     # 약하게
    2: (140, 40),     # 보통 (기본)
    3: (110, 80),     # 강하게
    4: (80, 150),     # 아주 강하게
}
DEFAULT_LEVEL = 2


def _hue_dist(hue, center):
    d = np.abs(hue.astype(np.int16) - int(center))
    return np.minimum(d, 180 - d)


def color_mask(flat, hues=None):
    """채도가 높은(색이 있는) 픽셀. hues를 주면 그 색상 근처(±HUE_TOL)인 것만."""
    hsv = cv2.cvtColor(flat, cv2.COLOR_RGB2HSV)
    m = (hsv[..., 1] >= SAT_MIN) & (hsv[..., 2] >= VAL_MIN)
    if hues is not None:
        near = np.zeros(m.shape, bool)
        for c in hues:
            near |= _hue_dist(hsv[..., 0], c) <= HUE_TOL
        m &= near
    return m


def extract_palette(rgb):
    """그림에 있는 주요 색(검정·회색 제외)을 많은 순서로 [{hue, rgb(#rrggbb), share}] 로 돌려준다.
    같은 색의 색조 변화는 하나로 묶고, 서로 1.5*HUE_TOL 안의 색은 따로 내지 않는다. 밝은 색(종이 색·연한 음영)은 뺀다."""
    flat = flatten_lighting(rgb)
    hsv = cv2.cvtColor(flat, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(flat, cv2.COLOR_RGB2GRAY)
    colored = (hsv[..., 1] >= SAT_MIN) & (hsv[..., 2] >= VAL_MIN) & (gray < PALETTE_GRAY_MAX)
    hue = hsv[..., 0][colored].astype(np.int32)
    pix = flat[colored]
    min_count = max(MIN_INK_PIXELS, int(PALETTE_MIN_RATIO * colored.size))
    centers = np.arange(180)
    avail = np.ones(hue.shape, bool)
    blocked = np.zeros(180, bool)
    out = []
    for _ in range(PALETTE_MAX):
        if not avail.any():
            break
        hist = np.bincount(hue[avail], minlength=180).astype(np.int64)
        score = sum(np.roll(hist, k) for k in range(-HUE_TOL, HUE_TOL + 1))
        score[blocked] = 0
        c = int(score.argmax())
        if score[c] < min_count:
            break
        members = _hue_dist(hue, c) <= HUE_TOL
        r, g, b = (int(round(v)) for v in pix[members].mean(axis=0))
        out.append({"hue": c, "rgb": f"#{r:02x}{g:02x}{b:02x}", "share": round(float(members.sum()) / colored.size, 4)})
        avail &= _hue_dist(hue, c) > HUE_TOL * 3 // 2
        blocked |= _hue_dist(centers, c) <= HUE_TOL * 3 // 2
    return out


def clean_figure(rgb, level=DEFAULT_LEVEL, keep_color=False, erase_hues=None):
    """RGB 배열 → (정리한 회색조 배열, 정리 전 잉크 수, 정리 후 잉크 수).
    조명 평탄화 → 색 필기 제거 → 기준보다 어두운 픽셀만 남김 → 작은 덩어리(종이 점, 연한 낙서 조각) 제거.
    keep_color=True면 색 필기 제거를 건너뛴다. 색은 낙서일 수도, 인쇄된 그림(파란 곡선, 컬러 삽화)일
    수도 있어 기계가 가를 수 없으므로, 색을 지울지는 사용자가 고른다. 이때 색 선은 밝기로만 판단한다.
    erase_hues(색상 값 목록)를 주면 그 색 근처만 지우고 나머지 색은 밝기로 판단한다(keep_color는 무시)."""
    T, min_area = LEVELS[level]
    flat = flatten_lighting(rgb)
    # 과제거 판정의 기준이 되는 정리 전 잉크는 색을 지우기 전에 센다(색을 지운 뒤에 세면 지워진 색은 애초에 안 세어져서
    # 곡선이 통째로 사라져도 문제없음으로 통과한다).
    ink_before = int(np.count_nonzero(cv2.cvtColor(flat, cv2.COLOR_RGB2GRAY) < LEVELS[DEFAULT_LEVEL][0]))
    if erase_hues is not None or not keep_color:
        color = color_mask(flat, erase_hues).astype(np.uint8) * 255
        color = cv2.dilate(color, np.ones((3, 3), np.uint8))   # 안티앨리어싱 테두리까지
        flat = flat.copy()
        flat[color > 0] = 255
    gray = cv2.cvtColor(flat, cv2.COLOR_RGB2GRAY)

    dark = (gray < T).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    scale = (gray.shape[1] / 1000.0) ** 2
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= min_area * scale
    mask = cv2.dilate(keep[lab].astype(np.uint8), np.ones((5, 5), np.uint8))   # 안티앨리어싱 테두리
    stretched = np.clip((gray.astype(np.float32) - T * 0.4) * 255.0 / (T * 1.1 - T * 0.4), 0, 255).astype(np.uint8)
    out = np.where(mask > 0, stretched, 255).astype(np.uint8)
    return out, ink_before, int(np.count_nonzero(out < T))


class FigureCleaner:
    """포트 FigureCleaner의 실제 구현. 실패하면 예외(DecodeError 포함), 과제거면 clean=None."""

    def palette(self, raw: bytes) -> list:
        """그림의 주요 색 견본(사용자가 지울 색을 고르는 용도). 색이 없으면 빈 목록."""
        return extract_palette(np.array(decode_image(raw)))

    def clean(self, raw: bytes, level: int = DEFAULT_LEVEL, keep_color: bool = False, erase_hues=None) -> CleanResult:
        """level: 정리 세기 1~4. 기본 단계에서만 과제거 판정을 쓰고, 사용자가 고른 단계는 그대로 따른다.
        keep_color: 색 필기를 지우지 않고 밝기로만 정리한다(색이 인쇄된 그림용)."""
        im = decode_image(raw)
        out, before, after = clean_figure(np.array(im), level, keep_color, erase_hues)
        # 지울 색을 사용자가 직접 고른 경우(erase_hues)는 과제거로 보지 않고 그대로 따른다
        if level == DEFAULT_LEVEL and erase_hues is None and (before < MIN_INK_PIXELS or after < MIN_KEEP_RATIO * before):
            return CleanResult(clean=None, content_type=None)
        buf = io.BytesIO()
        Image.fromarray(out, "L").save(buf, "PNG")
        return CleanResult(clean=buf.getvalue(), content_type="image/png")
