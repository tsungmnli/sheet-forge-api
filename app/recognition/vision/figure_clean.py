"""④ 그림 정리(작업자 전용, LLM 없음). 설계 7장.

조명 평탄화 → 색 필기 제거(채도 높은 픽셀을 흰색으로) → 약한 이진화(선 근처만 남기고 배경을 흰색으로, 안티앨리어싱은 유지).
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
_LEVEL_LO, _LEVEL_HI = 90, 200
DARK_LEVEL = 100       # 이보다 어두운 픽셀은 큰 검은 면의 안쪽이어도 남긴다(과제거 판정에는 쓰지 않음)


def _ink(gray):
    """적응형 이진화로 본 잉크 마스크(255=잉크)."""
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)


def clean_figure(rgb):
    """RGB 배열 → (정리한 회색조 배열, 정리 전 잉크 수, 정리 후 잉크 수)."""
    flat = flatten_lighting(rgb)
    ink_before = int(np.count_nonzero(_ink(cv2.cvtColor(flat, cv2.COLOR_RGB2GRAY))))
    hsv = cv2.cvtColor(flat, cv2.COLOR_RGB2HSV)
    color = ((hsv[..., 1] >= SAT_MIN) & (hsv[..., 2] >= VAL_MIN)).astype(np.uint8) * 255
    color = cv2.dilate(color, np.ones((3, 3), np.uint8))   # 안티앨리어싱 테두리까지
    flat = flat.copy()
    flat[color > 0] = 255
    gray = cv2.cvtColor(flat, cv2.COLOR_RGB2GRAY)
    ink = _ink(gray)
    ink_after = int(np.count_nonzero(ink))
    near = cv2.bitwise_or(cv2.dilate(ink, np.ones((5, 5), np.uint8)), (gray < DARK_LEVEL).astype(np.uint8) * 255)
    stretched = np.clip((gray.astype(np.float32) - _LEVEL_LO) * 255.0 / (_LEVEL_HI - _LEVEL_LO), 0, 255).astype(np.uint8)
    return np.where(near > 0, stretched, 255).astype(np.uint8), ink_before, ink_after


class FigureCleaner:
    """포트 FigureCleaner의 실제 구현. 실패하면 예외(DecodeError 포함), 과제거면 clean=None."""

    def clean(self, raw: bytes) -> CleanResult:
        im = decode_image(raw)
        out, before, after = clean_figure(np.array(im))
        if before < MIN_INK_PIXELS or after < MIN_KEEP_RATIO * before:
            return CleanResult(clean=None, content_type=None)
        buf = io.BytesIO()
        Image.fromarray(out, "L").save(buf, "PNG")
        return CleanResult(clean=buf.getvalue(), content_type="image/png")
