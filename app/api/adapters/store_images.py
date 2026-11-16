"""이미지 저장소(ImageStore)에서 그림을 읽는 어댑터 (REST 설계 5.7). 라이브러리 ImageProvider(`.get(ref)`)와 호환.

- 없으면 None → 라이브러리가 "그림을 찾지 못함"으로 보고한다.
- 저장소 오류·크기 한계 초과는 예외 → 라이브러리가 "그림을 불러오지 못함"으로 보고한다(예외 메시지에 이미지 내용은 담지 않는다).
- PNG가 아니면 크기 0으로 돌려 라이브러리의 PNG 검사가 "PNG가 아님"으로 보고하게 한다.
"""
from ...export.hwpx.images import ImageData
from .inline import png_size


class StoreImages:
    def __init__(self, store, max_bytes: int, max_px: int):
        self._store = store
        self._max_bytes = max_bytes
        self._max_px = max_px
        self._cache: dict = {}

    def get(self, ref):
        if ref in self._cache:
            return self._cache[ref]
        got = self._store.get(ref)  # StorageError는 그대로 올린다
        if got is None:
            return None
        raw = got[0]
        if len(raw) > self._max_bytes:
            raise ValueError("이미지가 크기 한계를 넘음")
        size = png_size(raw)
        if size is None:
            img = ImageData(raw, 0, 0)
        elif not (0 < size[0] <= self._max_px and 0 < size[1] <= self._max_px):
            raise ValueError("이미지 픽셀 크기가 한계를 넘음")
        else:
            img = ImageData(raw, size[0], size[1])
        self._cache[ref] = img
        return img
