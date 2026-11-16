"""ImageProvider 계약 (설계 4·11장). figure 참조(ref) → PNG bytes + 픽셀 크기. 서버는 파일·DB를 직접 읽지 않는다."""
from dataclasses import dataclass

PNG_SIG = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class ImageData:
    png: bytes
    width_px: int
    height_px: int


def load_image(provider, ref):
    """provider: `ref -> ImageData | None`인 callable, 또는 같은 동작의 `.get(ref)`를 가진 객체.
    반환: (ImageData, None) 또는 (None, 실패 이유)."""
    if provider is None:
        return None, "ImageProvider가 없음"
    if not ref:
        return None, "그림 참조(ref)가 없음"
    fn = provider if callable(provider) else provider.get
    try:
        img = fn(ref)
    except Exception as ex:  # 저장소 오류도 예외가 아니라 보고로 알린다(설계 1장 4)
        return None, f"그림을 불러오지 못함: {ref} ({ex})"
    if img is None:
        return None, f"그림을 찾지 못함: {ref}"
    if not bytes(img.png[:8]) == PNG_SIG:
        return None, f"PNG가 아님: {ref}"
    if img.width_px <= 0 or img.height_px <= 0:
        return None, f"그림 픽셀 크기가 올바르지 않음: {ref}"
    return img, None
