"""요청 본문에서 이미지를 읽는 어댑터 (설계 3장). 라이브러리 ImageProvider(`.get(ref)`)와 호환."""
import base64
import binascii
import struct

from ...export.hwpx.images import PNG_SIG, ImageData
from ..errors import ApiError


def png_size(data: bytes):
    """PNG 헤더(IHDR)에서 (폭, 높이) 픽셀. PNG가 아니면 None. 래스터화하지 않는다 [설계 7장]."""
    if len(data) < 24 or data[:8] != PNG_SIG or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


class InlineImages:
    def __init__(self, images: dict, max_bytes: int, max_px: int):
        self._d: dict = {}
        for ref, b64 in images.items():
            if len(b64) * 3 // 4 > max_bytes + 3:  # 디코딩 전에 크기부터 거른다
                raise ApiError(413, "PAYLOAD_TOO_LARGE", f"이미지가 너무 큼: {ref}", [{"ref": ref}])
            try:
                raw = base64.b64decode(b64, validate=True)
            except (binascii.Error, ValueError):
                raise ApiError(422, "IMAGE_INVALID", f"base64가 올바르지 않음: {ref}", [{"ref": ref}]) from None
            if len(raw) > max_bytes:
                raise ApiError(413, "PAYLOAD_TOO_LARGE", f"이미지가 너무 큼: {ref}", [{"ref": ref}])
            size = png_size(raw)
            if size is None:
                raise ApiError(422, "IMAGE_INVALID", f"PNG가 아님: {ref}", [{"ref": ref}])
            if not (0 < size[0] <= max_px and 0 < size[1] <= max_px):
                raise ApiError(413, "PAYLOAD_TOO_LARGE", f"이미지 픽셀 크기가 한계({max_px}) 밖: {ref}", [{"ref": ref}])
            self._d[ref] = ImageData(raw, size[0], size[1])

    def get(self, ref):
        return self._d.get(ref)
