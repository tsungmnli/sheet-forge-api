"""가짜 PageProcessor: 보정 없이 고정된 문제 칸 6개(2열 × 3행)를 돌려준다. B5에서 실제 구현으로 바꾼다."""
import io

from .ports import CleanResult, PageResult, ReadResult, SegmentDraft

_COLS = ((0.05, 0.48), (0.52, 0.95))
_ROWS = ((0.06, 0.32), (0.35, 0.62), (0.65, 0.92))


def _size(data: bytes):
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:  # noqa: BLE001 — HEIC 등 Pillow가 못 여는 형식은 크기 없이 진행
        return None, None


class FakePageProcessor:
    def process(self, data: bytes, content_type: str) -> PageResult:
        w, h = _size(data)
        segments, n = [], 1
        for x0, x1 in _COLS:
            for y0, y1 in _ROWS:
                segments.append(SegmentDraft(bbox=(x0, y0, x1, y1), number=f"{n:02d}"))
                n += 1
        return PageResult(width=w, height=h, segments=segments)


class FakeRecognizer:
    """가짜 Recognizer: 크롭을 보지 않고 고정된 문제를 돌려준다. tier가 글에 들어가 다시 읽기를 구분할 수 있다. B5에서 교체."""

    def read(self, crop: bytes, tier: str = "default") -> ReadResult:
        def text(v):
            return {"t": "text", "v": v}

        stem = [{"type": "paragraph", "inlines": [
            text(f"가짜 읽기({tier}) 결과입니다. 함수 "),
            {"t": "math", "latex": "f(x)=x^{2}+1", "conf": 0.5},
            text("에 대하여 "), {"t": "math", "latex": "f(2)"}, text("의 값은?")]}]
        choices = {"items": [[text(str(n))] for n in (1, 3, 5, 7, 9)], "layout": "auto"}
        return ReadResult(content={"stem": stem, "choices": choices, "figures": []},
                          meta={"engine": "fake", "tier": tier})


class FakeFigureCleaner:
    """가짜 FigureCleaner: 정리 없이 원본 그림을 그대로 정리본으로 돌려준다. B5에서 교체."""

    def clean(self, raw: bytes, level: int = 2, keep_color: bool = False, erase_hues=None) -> CleanResult:
        return CleanResult(clean=raw, content_type=None)

    def palette(self, raw: bytes) -> list:
        return []
