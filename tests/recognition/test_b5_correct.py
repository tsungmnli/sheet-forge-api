"""B5-1b: 보정(꼭짓점 검출, 기울기 폴백, 투시 변환, 조명 평탄화). 합성 이미지로 확인한다."""
import unittest

import cv2
import numpy as np
from PIL import Image

from app.recognition.vision import correct as C


def _page(w=600, h=800, seed=1):
    """흰 종이에 글줄 같은 검은 막대를 그린다."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 245, np.uint8)
    for y in range(60, h - 40, 34):
        x = 50
        while x < w - 80:
            n = int(rng.integers(30, 120))
            cv2.rectangle(img, (x, y), (min(x + n, w - 50), y + 12), (20, 20, 20), -1)
            x += n + 14
    return img


def _photo(corners, size=(1200, 1000), bg=(90, 70, 50)):
    """종이 이미지를 배경 위의 사각형(corners 비율)으로 투시 변환해 붙인다."""
    page = _page()
    ph, pw = page.shape[:2]
    w, h = size
    dst = np.array(corners, np.float32) * np.array([w, h], np.float32)
    src = np.array([[0, 0], [pw - 1, 0], [pw - 1, ph - 1], [0, ph - 1]], np.float32)
    canvas = np.full((h, w, 3), bg, np.uint8)
    warped = cv2.warpPerspective(page, cv2.getPerspectiveTransform(src, dst), (w, h))
    mask = cv2.warpPerspective(np.full((ph, pw), 255, np.uint8), cv2.getPerspectiveTransform(src, dst), (w, h))
    canvas[mask > 0] = warped[mask > 0]
    return canvas


QUAD = [(0.18, 0.10), (0.80, 0.14), (0.84, 0.90), (0.14, 0.86)]


class CorrectTest(unittest.TestCase):
    def test_downscale(self):
        im = Image.new("RGB", (4000, 2000))
        self.assertEqual(C.downscale(im).size, (3000, 1500))
        self.assertEqual(C.downscale(Image.new("RGB", (100, 50))).size, (100, 50))

    def test_find_corners_on_desk_photo(self):
        found = C.find_corners(_photo(QUAD))
        self.assertIsNotNone(found)
        for (fx, fy), (ex, ey) in zip(found, QUAD):
            self.assertLess(abs(fx - ex), 0.03)
            self.assertLess(abs(fy - ey), 0.03)

    def test_correct_page_warps_to_page_shape(self):
        res = C.correct_page(Image.fromarray(_photo(QUAD)))
        self.assertTrue(res.found and res.auto)
        w, h = res.image.size
        q = np.array(QUAD) * np.array([1200, 1000])  # 사진 안 사각형의 실제 픽셀 길이로 기대 비율을 계산
        want = max(np.linalg.norm(q[0] - q[1]), np.linalg.norm(q[3] - q[2])) / max(
            np.linalg.norm(q[0] - q[3]), np.linalg.norm(q[1] - q[2]))
        self.assertAlmostEqual(w / h, want, delta=0.1)
        # 배경(어두운 책상)이 거의 남지 않아야 한다
        arr = np.array(res.image).astype(int)
        self.assertLess(float((arr.mean(axis=2) < 120).mean()), 0.45)

    def test_fallback_deskews_when_no_page_edges(self):
        tilted = cv2.warpAffine(_page(), cv2.getRotationMatrix2D((300, 400), 3.0, 1.0), (600, 800),
                                borderMode=cv2.BORDER_REPLICATE)
        res = C.correct_page(Image.fromarray(tilted))
        self.assertFalse(res.found)
        self.assertEqual(res.corners, C.FULL)
        self.assertLess(abs(C.estimate_skew(np.array(res.image))), 1.0)

    def test_fallback_ignores_background_pattern(self):
        """글줄 없이 비스듬한 줄무늬(나뭇결·폰 화면 테두리 같은 것)만 있으면 돌리지 않는다."""
        img = np.full((800, 600, 3), 200, np.uint8)
        for y in range(-200, 1000, 18):  # 약 12°(탐색 범위 밖) 기운 줄무늬
            cv2.line(img, (0, y), (600, y + 128), (60, 40, 20), 5)
        self.assertEqual(C.estimate_skew(img), 0.0)

    def test_fallback_records_skew(self):
        tilted = cv2.warpAffine(_page(), cv2.getRotationMatrix2D((300, 400), 3.0, 1.0), (600, 800),
                                borderMode=cv2.BORDER_REPLICATE)
        res = C.correct_page(Image.fromarray(tilted))
        self.assertAlmostEqual(abs(res.skew), 3.0, delta=1.0)

    def test_apply_correction_modes(self):
        im = Image.fromarray(_photo(QUAD))
        plain = C.apply_correction(im, {"mode": "none", "rotation": 90})
        self.assertEqual(plain.image.size, (1000, 1200))  # 원본 크기 그대로, 90° 회전만
        self.assertEqual(plain.corners, C.FULL)
        manual = C.apply_correction(im, {"mode": "manual", "corners": QUAD})
        self.assertFalse(manual.auto)
        self.assertTrue(C.apply_correction(im, None).auto)
        info = C.applied_info(manual)
        self.assertEqual(len(info["corners"]), 4)
        with self.assertRaises(ValueError):
            C.apply_correction(im, {"mode": "weird"})

    def test_manual_corners_and_rotation(self):
        res = C.correct_page(Image.fromarray(_photo(QUAD)), corners=QUAD)
        self.assertFalse(res.auto)
        self.assertTrue(res.found)
        r90 = C.correct_page(Image.new("RGB", (300, 200), (240, 240, 240)), corners=C.FULL, rotation=90)
        self.assertEqual(r90.image.size, (200, 300))
        with self.assertRaises(ValueError):
            C.correct_page(Image.new("RGB", (10, 10)), rotation=45)

    def test_flatten_lighting_reduces_shading(self):
        page = _page().astype(np.float32)
        ramp = np.linspace(0.45, 1.0, page.shape[1], dtype=np.float32)[None, :, None]
        shaded = np.clip(page * ramp, 0, 255).astype(np.uint8)
        flat = C.flatten_lighting(shaded)

        def bg_spread(a):  # 글자 없는 가장자리 세로 띠의 좌우 밝기 차
            return abs(float(a[:, 10:30].mean()) - float(a[:, -30:-10].mean()))

        self.assertLess(bg_spread(flat), bg_spread(shaded) * 0.5)


if __name__ == "__main__":
    unittest.main()
