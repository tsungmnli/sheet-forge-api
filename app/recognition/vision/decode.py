"""사진 디코드(작업자 전용). JPEG·PNG·WebP·HEIC → RGB 이미지, EXIF 회전 적용.

HEIC는 pillow-heif가 있으면 연다. 실패 원인은 종류만 DecodeError로 알리고, 사진 내용은 어디에도 남기지 않는다.
"""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

_heif_ready = None


class DecodeError(ValueError):
    """읽을 수 없는 사진. 메시지는 원인 종류만 담는다(unsupported, too_large, DecompressionBombError 등)."""


def _register_heif():
    global _heif_ready
    if _heif_ready is None:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            _heif_ready = True
        except ImportError:
            _heif_ready = False
    return _heif_ready


def decode_image(data: bytes, max_side: int = 8000):
    """사진 바이트 → RGB PIL 이미지(EXIF 회전 적용). 한 변이 max_side를 넘으면 픽셀을 읽기 전에 거절한다."""
    _register_heif()
    try:
        with Image.open(io.BytesIO(data)) as im:
            if max(im.size) > max_side:
                raise DecodeError("too_large")
            im.load()
            return ImageOps.exif_transpose(im).convert("RGB")
    except DecodeError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        kind = "unsupported" if isinstance(e, UnidentifiedImageError) else type(e).__name__
        raise DecodeError(kind) from None


def encode_jpeg(im, quality: int = 90) -> bytes:
    out = io.BytesIO()
    im.convert("RGB").save(out, "JPEG", quality=quality)
    return out.getvalue()
