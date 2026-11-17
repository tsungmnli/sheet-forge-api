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


LEVELS = {            # level: (어두움 기준 T, 지울 덩어리 최대 크기 min_area, 1000px 폭 기준)
    1: (170, 15),     # 약하게
    2: (140, 40),     # 보통 (기본)
    3: (110, 80),     # 강하게
    4: (80, 150),     # 아주 강하게
}
DEFAULT_LEVEL = 2


def clean_figure(rgb, level=DEFAULT_LEVEL):
    """RGB 배열 → (정리한 회색조 배열, 정리 전 잉크 수, 정리 후 잉크 수).
    조명 평탄화 → 색 필기 제거 → 기준보다 어두운 픽셀만 남김 → 작은 덩어리(종이 점, 연한 낙서 조각) 제거."""
    T, min_area = LEVELS[level]
    flat = flatten_lighting(rgb)
    hsv = cv2.cvtColor(flat, cv2.COLOR_RGB2HSV)
    color = ((hsv[..., 1] >= SAT_MIN) & (hsv[..., 2] >= VAL_MIN)).astype(np.uint8) * 255
    color = cv2.dilate(color, np.ones((3, 3), np.uint8))   # 안티앨리어싱 테두리까지
    flat = flat.copy()
    flat[color > 0] = 255
    gray = cv2.cvtColor(flat, cv2.COLOR_RGB2GRAY)

    ink_before = int(np.count_nonzero(gray < LEVELS[DEFAULT_LEVEL][0]))
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

    def clean(self, raw: bytes, level: int = DEFAULT_LEVEL) -> CleanResult:
        """level: 정리 세기 1~4. 기본 단계에서만 과제거 판정을 쓰고, 사용자가 고른 단계는 그대로 따른다."""
        im = decode_image(raw)
        out, before, after = clean_figure(np.array(im), level)
        if level == DEFAULT_LEVEL and (before < MIN_INK_PIXELS or after < MIN_KEEP_RATIO * before):
            return CleanResult(clean=None, content_type=None)
        buf = io.BytesIO()
        Image.fromarray(out, "L").save(buf, "PNG")
        return CleanResult(clean=buf.getvalue(), content_type="image/png")
