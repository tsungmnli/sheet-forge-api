"""① 보정(작업자 전용, LLM 없음): 축소 → 페이지 꼭짓점 → 투시 변환 → 조명 평탄화. 설계 4장.

꼭짓점은 (x, y) 0~1 비율이고 순서는 왼위·오른위·오른아래·왼아래다. 비율의 기준은 축소·90° 회전을 마친 입력이다.
꼭짓점을 못 찾으면 사진 전체를 페이지로 보고 기울기만 바로잡는다(found=False).
선생님이 고른 보정 설정(pages.correction)은 apply_correction이 받는다: mode auto | none(원본 그대로) | manual(꼭짓점 지정).
"""
import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

MAX_SIDE = 3000          # 긴 변 상한(설계 4장 2번)
MIN_AREA_RATIO = 0.25    # 페이지로 인정하는 최소 면적(이미지 대비)
_DETECT_SIDE = 1000      # 꼭짓점 검출은 이 크기로 줄여서 한다
_SKEW_SIDE = 800
_SKEW_RANGE = 10.0       # 기울기 탐색 범위(±도)
_SKEW_STEP = 0.5
_SKEW_MARGIN = 0.15      # 기울기는 가장자리(책상·폰 테두리)를 뺀 가운데에서만 잰다
_SKEW_MIN_GAIN = 1.15    # 0°보다 이만큼 뚜렷하게 나을 때만 돌린다
_SKEW_MAX_APPLY = _SKEW_RANGE - 2 * _SKEW_STEP  # 탐색 끝자락 각도는 배경 무늬일 가능성이 커서 버린다
_WHITE = (255, 255, 255)
MODES = ("auto", "none", "manual")
FULL = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


@dataclass(frozen=True)
class Correction:
    image: Image.Image   # 보정본(RGB)
    corners: list        # 쓴 꼭짓점 [(x, y)] 비율
    auto: bool           # True: 자동 결정, False: 호출한 쪽이 꼭짓점을 줌
    found: bool          # False: 자동 검출 실패, 사진 전체 + 기울기 보정으로 대신함
    rotation: int        # 적용한 90° 단위 회전(시계 방향)
    skew: float = 0.0    # found=False일 때 적용한 기울기 보정(도), 확신이 없으면 0


def downscale(im, max_side=MAX_SIDE):
    w, h = im.size
    s = max_side / max(w, h)
    if s >= 1:
        return im
    return im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)


def _order(pts):
    pts = np.asarray(pts, dtype=np.float32)
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def find_corners(rgb):
    """페이지 꼭짓점(비율) 4개, 못 찾으면 None. 그레이 → 블러 → 가장자리 → 윤곽 → 가장 큰 볼록 사각형."""
    h, w = rgb.shape[:2]
    s = _DETECT_SIDE / max(h, w)
    small = cv2.resize(rgb, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA) if s < 1 else rgb
    sh, sw = small.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 50, 150), np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(c) < MIN_AREA_RATIO * sw * sh:
            break
        hull = cv2.convexHull(c)
        approx = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            quad = approx.reshape(4, 2)
            if cv2.contourArea(quad) >= MIN_AREA_RATIO * sw * sh:
                best = quad
                break
    if best is None:
        return None
    return [(float(x) / sw, float(y) / sh) for x, y in _order(best)]


def estimate_skew(rgb):
    """글줄이 가로가 되도록 돌려야 하는 각도(도, cv2 회전 기준). 확신이 없으면 0.

    가운데 영역의 가로 투영 분산이 가장 큰 각도를 고른다. 아래 경우엔 돌리지 않는다(0):
    - 0°보다 분산이 뚜렷하게 크지 않다(글줄이 아니라 나뭇결·화면 무늬에 끌린 경우가 많다)
    - 고른 각도가 탐색 범위 끝자락이다(진짜 기울기라면 범위 안쪽에서 꼭짓점이 생긴다)
    """
    h, w = rgb.shape[:2]
    my, mx = round(h * _SKEW_MARGIN), round(w * _SKEW_MARGIN)
    core = rgb[my:h - my, mx:w - mx] if h - 2 * my > 20 and w - 2 * mx > 20 else rgb
    ch, cw = core.shape[:2]
    s = _SKEW_SIDE / max(ch, cw)
    small = cv2.resize(core, (max(1, round(cw * s)), max(1, round(ch * s))), interpolation=cv2.INTER_AREA) if s < 1 else core
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    ink = cv2.threshold(cv2.GaussianBlur(gray, (3, 3), 0), 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    sh, sw = ink.shape
    center = (sw / 2, sh / 2)
    best, best_score, zero_score = 0.0, -1.0, 0.0
    for a in np.arange(-_SKEW_RANGE, _SKEW_RANGE + 1e-9, _SKEW_STEP):
        r = cv2.warpAffine(ink, cv2.getRotationMatrix2D(center, float(a), 1.0), (sw, sh))
        score = float(np.var(r.sum(axis=1, dtype=np.float64)))
        if abs(a) < 1e-9:
            zero_score = score
        if score > best_score:
            best, best_score = float(a), score
    if abs(best) > _SKEW_MAX_APPLY or best_score < zero_score * _SKEW_MIN_GAIN:
        return 0.0
    return best


def _rotate_small(rgb, angle):
    """빈 모서리는 흰색으로 채운다(가장자리 픽셀 복제는 줄무늬를 만들어 읽기를 방해한다)."""
    if not angle:
        return rgb
    h, w = rgb.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(rgb, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=_WHITE)


def rotate_free(rgb, angle):
    """시계 방향 angle°(소수 가능)만큼 돌린다. 사진이 잘리지 않게 캔버스를 키우고 빈 곳은 흰색으로 채운다."""
    if not angle:
        return rgb
    h, w = rgb.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), -float(angle), 1.0)  # cv2는 반시계가 +
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = round(h * sin + w * cos), round(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(rgb, m, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=_WHITE)


def warp(rgb, corners):
    """꼭짓점(비율) 사각형을 반듯한 직사각형으로 편다. 출력 크기는 마주 보는 변 길이의 큰 쪽."""
    h, w = rgb.shape[:2]
    src = _order(np.array(corners, dtype=np.float32) * np.array([w, h], dtype=np.float32))
    tl, tr, br, bl = src
    out_w = max(2, round(max(math.dist(tl, tr), math.dist(bl, br))))
    out_h = max(2, round(max(math.dist(tl, bl), math.dist(tr, br))))
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(rgb, m, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def flatten_lighting(rgb):
    """밝기만 평탄화한다(접힘 그림자 완화). 큰 최대값 필터로 글자를 지운 배경 밝기를 추정해 나누고, 색은 유지하며 이진화하지 않는다."""
    h, w = rgb.shape[:2]
    s = 0.25
    small = cv2.resize(rgb, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    bg = cv2.dilate(gray, np.ones((15, 15), np.uint8))
    bg = cv2.GaussianBlur(bg, (0, 0), sigmaX=max(3.0, max(gray.shape) / 25))
    bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    gain = 255.0 / np.maximum(bg, 32.0)
    return np.clip(rgb.astype(np.float32) * gain[..., None], 0, 255).astype(np.uint8)


def correct_page(im, corners=None, rotation=0, angle=0.0):
    """PIL 이미지 → Correction. corners를 주면(웹의 꼭짓점 조정) 그 값을 그대로 쓴다. rotation은 시계 방향 90° 단위.
    angle은 보정이 끝난 결과에 더하는 미세 회전(시계 방향 °). 보정 전에 돌리면 꼭짓점 검출·기울기 추정·투시 변환이 도로 펴 버린다."""
    rotation = rotation % 360
    if rotation % 90:
        raise ValueError("rotation must be a multiple of 90")
    rgb = np.ascontiguousarray(np.array(downscale(im).convert("RGB")))
    if rotation:
        rgb = np.ascontiguousarray(np.rot90(rgb, k=-(rotation // 90) % 4))
    found, skew = True, 0.0
    if corners is not None:
        used = [tuple(map(float, p)) for p in corners]
        if any(len(p) != 2 for p in used):
            raise ValueError("corners must be (x, y) pairs")
        if len(used) != 4:
            raise ValueError("corners must have 4 points")
    else:
        used = find_corners(rgb)
        if used is None:
            found, used = False, list(FULL)
            skew = estimate_skew(rgb)
            rgb = _rotate_small(rgb, skew)
    page = warp(rgb, used)
    return Correction(image=Image.fromarray(rotate_free(flatten_lighting(page), angle)), corners=used,
                      auto=corners is None, found=found, rotation=rotation, skew=skew)


def plain_page(im, rotation=0, angle=0.0):
    """원본 그대로 쓰기: 축소와 회전(90° 단위 + 미세 angle)만 한다(투시 변환·기울기·조명 평탄화 없음)."""
    rotation = rotation % 360
    if rotation % 90:
        raise ValueError("rotation must be a multiple of 90")
    rgb = np.ascontiguousarray(np.array(downscale(im).convert("RGB")))
    if rotation:
        rgb = np.ascontiguousarray(np.rot90(rgb, k=-(rotation // 90) % 4))
    rgb = rotate_free(rgb, angle)
    return Correction(image=Image.fromarray(rgb), corners=list(FULL), auto=False, found=True, rotation=rotation)


def apply_correction(im, req=None):
    """보정 설정 dict(없으면 자동) → Correction. req: {mode, rotation, corners}. 값 검증은 API가 먼저 한다."""
    req = req or {}
    mode = req.get("mode") or "auto"
    rotation = int(req.get("rotation") or 0)
    angle = float(req.get("angle") or 0.0)
    if mode == "none":
        return plain_page(im, rotation, angle)
    if mode == "manual":
        return correct_page(im, corners=req.get("corners"), rotation=rotation)
    if mode == "auto":
        return correct_page(im, rotation=rotation, angle=angle)
    raise ValueError("unknown correction mode")


def applied_info(c):
    """실제로 쓴 보정 결과(pages.correction.applied에 저장해 웹 편집기의 시작점으로 쓴다)."""
    return {"corners": [[round(float(x), 5), round(float(y), 5)] for x, y in c.corners],
            "found": bool(c.found), "skew": round(float(c.skew), 2)}
