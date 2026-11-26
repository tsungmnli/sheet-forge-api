"""3단계: 그림 색 견본(palette)과 고른 색만 지우기(erase_hues). 합성 그림으로 확인한다."""
import io
import unittest

import cv2
import numpy as np
from PIL import Image

from app.recognition.vision.figure_clean import FigureCleaner, clean_figure, extract_palette

BLUE, RED = (30, 60, 230), (230, 30, 30)


def _figure():
    img = np.full((240, 320, 3), 250, np.uint8)
    cv2.rectangle(img, (180, 60), (290, 170), (20, 20, 20), 2)      # 검정 인쇄 선
    cv2.line(img, (20, 200), (160, 40), BLUE, 3)                    # 파란 곡선(인쇄된 것)
    cv2.line(img, (20, 30), (150, 220), RED, 3)                     # 빨간 낙서
    return img


def _png(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


def _hue(rgb):
    return int(cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2HSV)[0, 0, 0])


class FigurePaletteTest(unittest.TestCase):
    def test_palette_lists_blue_and_red_not_black(self):
        pal = extract_palette(_figure())
        self.assertEqual(len(pal), 2)
        hues = sorted(c["hue"] for c in pal)
        for want in (_hue(BLUE), _hue(RED)):
            self.assertTrue(any(min(abs(h - want), 180 - abs(h - want)) <= 12 for h in hues), (want, hues))
        for c in pal:
            self.assertRegex(c["rgb"], r"^#[0-9a-f]{6}$")
            self.assertGreater(c["share"], 0)

    def test_palette_empty_for_black_only_figure(self):
        img = np.full((240, 320, 3), 250, np.uint8)
        cv2.circle(img, (110, 120), 70, (20, 20, 20), 2)
        self.assertEqual(extract_palette(img), [])

    def test_erase_only_picked_hue(self):
        img = _figure()

        def dist(h, w):
            return min(abs(h - w), 180 - abs(h - w))

        red_hue = min((c["hue"] for c in extract_palette(img)), key=lambda h: dist(h, _hue(RED)))
        out, _, _ = clean_figure(img, 2, erase_hues=[red_hue])
        # 두 선이 겹치지 않는 곳에서 본다: 빨간 낙서 위(x=40, y≈59)는 흰색, 파란 곡선 위(x=130, y≈74)는 남는다
        self.assertGreater(int(out[55:64, 37:44].min()), 200)
        self.assertLess(int(out[71:78, 127:134].min()), 128)

    def test_picked_color_skips_over_removal_check(self):
        # 파란 면이 잉크 대부분이어도 사용자가 고른 색이면 정리본을 버리지 않는다(기본 단계 과제거 판정 제외)
        img = _figure()
        cv2.rectangle(img, (20, 20), (300, 220), BLUE, -1)
        c = FigureCleaner()
        self.assertIsNone(c.clean(_png(img)).clean)
        self.assertIsNotNone(c.clean(_png(img), erase_hues=[_hue(BLUE)]).clean)
        self.assertTrue(len(c.palette(_png(img))) >= 1)


if __name__ == "__main__":
    unittest.main()
