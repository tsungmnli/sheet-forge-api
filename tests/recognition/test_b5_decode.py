"""B5-1a: 사진 디코드(JPEG·PNG·EXIF 회전·크기 한계·HEIC)."""
import io
import unittest

from PIL import Image

from app.recognition.vision.decode import DecodeError, decode_image, encode_jpeg


def _jpeg(size=(40, 20), orientation=None):
    im = Image.new("RGB", size, (200, 30, 30))
    out = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        im.save(out, "JPEG", exif=exif)
    else:
        im.save(out, "JPEG")
    return out.getvalue()


class DecodeTest(unittest.TestCase):
    def test_jpeg_and_png(self):
        self.assertEqual(decode_image(_jpeg()).size, (40, 20))
        out = io.BytesIO()
        Image.new("RGBA", (10, 8), (0, 0, 0, 0)).save(out, "PNG")
        im = decode_image(out.getvalue())
        self.assertEqual((im.size, im.mode), ((10, 8), "RGB"))

    def test_exif_rotation_applied(self):
        # Orientation 6(시계 방향 90도 회전 필요): 가로 40×세로 20이 세로 20×가로 40이 된다
        self.assertEqual(decode_image(_jpeg(orientation=6)).size, (20, 40))

    def test_too_large_and_garbage(self):
        with self.assertRaises(DecodeError) as c:
            decode_image(_jpeg((100, 10)), max_side=50)
        self.assertEqual(str(c.exception), "too_large")
        with self.assertRaises(DecodeError):
            decode_image(b"not an image at all")

    def test_encode_roundtrip(self):
        self.assertEqual(decode_image(encode_jpeg(Image.new("RGB", (16, 9)))).size, (16, 9))

    def test_heic(self):
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            out = io.BytesIO()
            Image.new("RGB", (32, 24), (10, 120, 200)).save(out, "HEIF")
        except Exception as e:  # noqa: BLE001 — 설치·인코더 문제는 건너뛰고 이유를 보여 준다
            self.skipTest(f"HEIC 인코딩 불가: {type(e).__name__}")
        self.assertEqual(decode_image(out.getvalue()).size, (32, 24))


if __name__ == "__main__":
    unittest.main()
