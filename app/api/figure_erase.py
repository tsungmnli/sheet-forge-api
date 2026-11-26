"""낙서 지우개 결과(PNG) 검증. 브라우저가 지운 그림을 올리면 형식·크기·비율을 확인하고 정리본과 같은 회색조 PNG로 다시 만든다."""
import io

from PIL import Image, UnidentifiedImageError

from .errors import ApiError

MAX_SIDE = 4096          # 한 변 상한(브라우저는 가로 2000px 안팎으로 줄여 보낸다)
MAX_PIXELS = 12_000_000  # 압축 폭탄 방지
RATIO_TOLERANCE = 0.02   # 기준 그림과 가로세로 비율이 이만큼까지 달라도 받는다(줄이면서 생기는 반올림 오차)
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def erase_base_ref(fig: dict) -> str | None:
    """낙서 지우개가 손볼 그림의 ref. 화면에 보이는 그림과 같은 규칙이다(원본을 고른 그림은 raw_ref, 아니면 정리본,
    정리본이 없으면 원본). 정리 단계를 안 고른 그림(원본)이나 색이 남은 그림에서도 지울 수 있게 한다."""
    if fig.get("use") == "raw":
        return fig.get("raw_ref")
    return fig.get("clean_ref") or fig.get("raw_ref")


def _invalid() -> ApiError:
    return ApiError(422, "FIGURE_IMAGE_INVALID")


def prepare_erased(data: bytes, base: bytes, max_bytes: int) -> bytes:
    """data: 올라온 PNG, base: 지금 쓰는 정리본. 통과하면 저장할 회색조 PNG 바이트를 돌려준다."""
    if len(data) > max_bytes:
        raise ApiError(413, "FIGURE_IMAGE_TOO_LARGE")
    if not data.startswith(_PNG_MAGIC):
        raise _invalid()
    try:
        im = Image.open(io.BytesIO(data))
        w, h = im.size   # 픽셀을 읽기 전에 크기부터 본다
        if im.format != "PNG" or w < 1 or h < 1 or max(w, h) > MAX_SIDE or w * h > MAX_PIXELS:
            raise _invalid()
        bw, bh = Image.open(io.BytesIO(base)).size
        if abs((w / h) / (bw / bh) - 1) > RATIO_TOLERANCE:
            raise _invalid()
        im.load()
        if im.mode in ("RGBA", "LA", "P"):   # 투명하게 올라오면 흰 바탕에 얹는다
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(bg, im)
        out = io.BytesIO()
        im.convert("L").save(out, "PNG")
        return out.getvalue()
    except ApiError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise _invalid() from None
