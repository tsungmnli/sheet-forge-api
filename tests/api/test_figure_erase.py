"""낙서 지우개 PNG 검증(prepare_erased). 서버·DB 없이 돈다."""
import io

import pytest
from PIL import Image

from app.api.errors import ApiError
from app.api.figure_erase import erase_base_ref, prepare_erased


def _png(size, mode="L", color=255):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


BASE = _png((400, 200))
LIMIT = 5 * 1024 * 1024


def test_ok_and_same_ratio_scaled():
    out = prepare_erased(_png((200, 100)), BASE, LIMIT)
    im = Image.open(io.BytesIO(out))
    assert im.format == "PNG" and im.mode == "L" and im.size == (200, 100)


def test_rgba_goes_onto_white():
    out = prepare_erased(_png((400, 200), "RGBA", (0, 0, 0, 0)), BASE, LIMIT)
    assert Image.open(io.BytesIO(out)).getpixel((5, 5)) == 255


@pytest.mark.parametrize("data,status,code", [
    (b"not a png", 422, "FIGURE_IMAGE_INVALID"),
    (_png((400, 400)), 422, "FIGURE_IMAGE_INVALID"),           # 비율이 다름
    (_png((5000, 2500)), 422, "FIGURE_IMAGE_INVALID"),         # 한 변 상한 초과
    (BASE[:60], 422, "FIGURE_IMAGE_INVALID"),                  # 잘린 PNG
])
def test_rejects(data, status, code):
    with pytest.raises(ApiError) as e:
        prepare_erased(data, BASE, LIMIT)
    assert (e.value.status, e.value.code) == (status, code)


@pytest.mark.parametrize("fig,ref", [
    ({"use": "clean", "clean_ref": "c", "raw_ref": "r"}, "c"),   # 정리본이 있으면 정리본 위에서
    ({"use": "clean", "clean_ref": None, "raw_ref": "r"}, "r"),  # 정리 단계를 안 고른 그림은 원본 위에서
    ({"use": "raw", "clean_ref": "c", "raw_ref": "r"}, "r"),     # 원본을 쓰는 그림은 보이는 그대로 원본 위에서
    ({"use": "clean", "clean_ref": None, "raw_ref": None}, None),
])
def test_erase_base_ref(fig, ref):
    assert erase_base_ref(fig) == ref


def test_too_large():
    with pytest.raises(ApiError) as e:
        prepare_erased(BASE, BASE, 10)
    assert (e.value.status, e.value.code) == (413, "FIGURE_IMAGE_TOO_LARGE")
