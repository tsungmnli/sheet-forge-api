"""B5-1c: 그림 정리(색 필기 제거, 과제거 시 원본, 실패). 합성 그림으로 확인한다."""
import io
import unittest

import cv2
import numpy as np
from PIL import Image

from app.recognition.vision.decode import DecodeError
from app.recognition.vision.figure_clean import FigureCleaner, clean_figure


def _figure(line=(20, 20, 20)):
    img = np.full((240, 320, 3), 250, np.uint8)
    cv2.circle(img, (110, 120), 70, line, 2)
    cv2.line(img, (30, 200), (300, 40), line, 2)
    cv2.rectangle(img, (180, 60), (290, 170), line, 2)
    return img


def _png(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return buf.getvalue()


class FigureCleanTest(unittest.TestCase):
    def test_color_scribble_removed_and_lines_kept(self):
        img = _figure()
        # 낙서가 잉크의 대부분을 차지하면 과제거(인쇄된 색 그림)로 보고 정리본을 버리므로, 낙서는 잉크의 절반 아래로 둔다
        cv2.line(img, (20, 30), (300, 220), (230, 30, 30), 3)      # 빨간 펜
        cv2.rectangle(img, (100, 100), (140, 125), (60, 80, 230), -1)  # 파란 형광펜 면
        res = FigureCleaner().clean(_png(img))
        self.assertIsNotNone(res.clean)
        self.assertEqual(res.content_type, "image/png")
        out = np.array(Image.open(io.BytesIO(res.clean)))
        base, _, _ = clean_figure(_figure())
        # 검정 선과 겹치지 않는 빨간 선 자리(60,57)와 파란 면 안쪽(120,110)은 흰색이 된다
        self.assertGreater(int(out[53:62, 56:65].min()), 200)
        self.assertGreater(int(out[106:115, 116:125].min()), 200)
        dark_ratio = float((out < 128).mean())
        base_ratio = float((base < 128).mean())
        self.assertGreater(dark_ratio, base_ratio * 0.6)
        self.assertLess(dark_ratio, base_ratio * 1.8)

    def test_fully_colored_figure_is_over_removed(self):
        res = FigureCleaner().clean(_png(_figure(line=(30, 60, 230))))
        self.assertIsNone(res.clean)

    def test_over_removal_counts_ink_before_color_removal(self):
        # 정리 전 잉크를 색 제거 뒤에 세면 지워진 색은 안 세어져 과제거가 안 잡힌다. 검정 선은 조금, 파란 면은 크게
        # 있는 그림에서 색을 지우면 잉크 대부분이 사라지므로 기본 단계는 정리본을 버려야 한다.
        img = _figure()
        cv2.rectangle(img, (20, 20), (300, 220), (60, 80, 230), -1)
        res = FigureCleaner().clean(_png(img))
        self.assertIsNone(res.clean)
        # 색 유지를 고르면 같은 그림도 버리지 않는다(밝기로만 판단)
        self.assertIsNotNone(FigureCleaner().clean(_png(img), keep_color=True).clean)

    def test_keep_color_keeps_printed_color_lines(self):
        # 파란색으로 인쇄된 그림: 기본(색 제거)은 지워 버리지만, keep_color면 선이 남는다
        img = _figure(line=(30, 60, 230))
        res = FigureCleaner().clean(_png(img), keep_color=True)
        self.assertIsNotNone(res.clean)
        out = np.array(Image.open(io.BytesIO(res.clean)))
        base, _, _ = clean_figure(_figure(line=(20, 20, 20)))
        self.assertGreater(float((out < 128).mean()), float((base < 128).mean()) * 0.6)
        for lv in (1, 3):   # 사용자가 고른 단계도 선을 남긴다(4단계는 밝기 기준이 엄격해 중간 밝기 파랑은 사라질 수 있다)
            o, _, _ = clean_figure(img, lv, keep_color=True)
            self.assertGreater(float((o < 128).mean()), 0.005)

    def test_keep_color_does_not_change_default(self):
        img = _figure()
        a, _, _ = clean_figure(img)
        b, _, _ = clean_figure(img, keep_color=False)
        self.assertTrue(np.array_equal(a, b))

    def test_blank_image_and_garbage(self):
        self.assertIsNone(FigureCleaner().clean(_png(np.full((50, 50, 3), 255, np.uint8))).clean)
        with self.assertRaises(DecodeError):
            FigureCleaner().clean(b"nope")

    def test_solid_dark_fill_is_kept(self):
        # 큰 검은 면(예: 색칠한 도형, 검은 상자)의 안쪽이 점무늬나 구멍이 되면 안 된다
        img = _figure()
        cv2.rectangle(img, (200, 150), (290, 220), (15, 15, 15), -1)
        res = FigureCleaner().clean(_png(img))
        self.assertIsNotNone(res.clean)
        out = np.array(Image.open(io.BytesIO(res.clean)))
        self.assertLess(float(out[165:205, 215:275].mean()), 60)


if __name__ == "__main__":
    unittest.main()
