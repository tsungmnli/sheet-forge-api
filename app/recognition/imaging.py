"""이미지 자르기(작업자 전용: 사진 해석은 격리된 작업자에서만 한다, 웹 REST API 설계 10장)."""
import io
import math

from PIL import Image


def crop_region(data: bytes, bbox, margin: float = 0.0, fmt: str = "JPEG"):
    """bbox=[x0,y0,x1,y1](0~1 비율)을 margin(전체 폭·높이 기준 비율)만큼 늘려 잘라 (bytes, content_type, 실제 상자)를 돌려준다.

    실제 상자는 잘라 낸 범위의 비율 좌표이며, 그림 범위(크롭 안 비율)를 사진 좌표로 옮기는 데 쓴다.
    """
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        w, h = im.size
        x0, y0 = max(0.0, bbox[0] - margin), max(0.0, bbox[1] - margin)
        x1, y1 = min(1.0, bbox[2] + margin), min(1.0, bbox[3] + margin)
        left, top = min(int(x0 * w), w - 1), min(int(y0 * h), h - 1)
        right = min(w, max(left + 1, math.ceil(x1 * w)))
        bottom = min(h, max(top + 1, math.ceil(y1 * h)))
        piece = im.crop((left, top, right, bottom))
        out = io.BytesIO()
        if fmt == "PNG":
            piece.save(out, "PNG")
            content_type = "image/png"
        else:
            piece.convert("RGB").save(out, "JPEG", quality=90)
            content_type = "image/jpeg"
    return out.getvalue(), content_type, [x0, y0, x1, y1]


def figure_page_box(crop_box, rel_bbox):
    """크롭 안 비율 좌표(rel_bbox)를 사진 비율 좌표로 옮긴다. crop_box는 crop_region이 돌려준 실제 상자."""
    cw, ch = crop_box[2] - crop_box[0], crop_box[3] - crop_box[1]
    return [crop_box[0] + rel_bbox[0] * cw, crop_box[1] + rel_bbox[1] * ch,
            crop_box[0] + rel_bbox[2] * cw, crop_box[1] + rel_bbox[3] * ch]
