"""① 보정(작업자 전용, LLM 없음): 축소 → 페이지 꼭짓점 → 투시 변환 → 조명 평탄화. 설계 4장.

꼭짓점은 (x, y) 0~1 비율이고 순서는 왼위·오른위·오른아래·왼아래다. 비율의 기준은 축소·90° 회전을 마친 입력이다.
꼭짓점을 못 찾으면 사진 전체를 페이지로 보고 기울기만 바로잡는다(found=False).
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
FULL = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


@dataclass(frozen=True)
class Correction:
    image: Image.Image   # 보정본(RGB)
    corners: list        # 쓴 꼭짓점 [(x, y)] 비율
    auto: bool           # True: 자동 결정, False: 호출한 쪽이 꼭짓점을 줌
    found: bool          # False: 자동 검출 실패, 사진 전체 + 기울기 보정으로 대신함
    rotation: int        # 적용한 90° 단위 회전(시계 방향)


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
    """글줄이 가로가 되도록 돌려야 하는 각도(도, cv2 회전 기준). 가로 투영의 분산이 가장 큰 각도를 고른다."""
    h, w = rgb.shape[:2]
    s = _SKEW_SIDE / max(h, w)
    small = cv2.resize(rgb, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA) if s < 1 else rgb
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    ink = cv2.threshold(cv2.GaussianBlur(gray, (3, 3), 0), 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    sh, sw = ink.shape
    center = (sw / 2, sh / 2)
    best, best_score = 0.0, -1.0
    for a in np.arange(-_SKEW_RANGE, _SKEW_RANGE + 1e-9, _SKEW_STEP):
        r = cv2.warpAffine(ink, cv2.getRotationMatrix2D(center, float(a), 1.0), (sw, sh))
        score = float(np.var(r.sum(axis=1, dtype=np.float64)))
        if score > best_score:
            best, best_score = float(a), score
    return best


def _rotate_small(rgb, angle):
    h, w = rgb.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(rgb, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


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


def correct_page(im, corners=None, rotation=0):
    """PIL 이미지 → Correction. corners를 주면(웹의 꼭짓점 조정) 그 값을 그대로 쓴다. rotation은 시계 방향 90° 단위."""
    rotation = rotation % 360
    if rotation % 90:
        raise ValueError("rotation must be a multiple of 90")
    rgb = np.ascontiguousarray(np.array(downscale(im).convert("RGB")))
    if rotation:
        rgb = np.ascontiguousarray(np.rot90(rgb, k=-(rotation // 90) % 4))
    found = True
    if corners is not None:
        used = [tuple(map(float, p)) for p in corners]
        if len(used) != 4:
            raise ValueError("corners must have 4 points")
    else:
        used = find_corners(rgb)
        if used is None:
            found, used = False, list(FULL)
            rgb = _rotate_small(rgb, estimate_skew(rgb))
    page = warp(rgb, used)
    return Correction(image=Image.fromarray(flatten_lighting(page)), corners=used,
                      auto=corners is None, found=found, rotation=rotation)
