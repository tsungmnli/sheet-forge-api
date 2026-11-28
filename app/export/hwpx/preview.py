"""배치 스케치 미리보기에 쓰는 값(웹 PagePreview). 한글 파일을 만드는 계산과 같은 함수를 불러 화면과 결과가 어긋나지 않게 한다.
단위는 모두 mm. 제목 상자 높이는 줄 수로 추정한 값이다(TITLE_BOX_HEIGHT_ESTIMATED와 같은 계산)."""
from .builders import clean_text, title_box_spec
from .layout import LayoutContext
from .preset import ExportPreset
from .section import (FOOTER_INNER_H, FOOTER_INNER_W, HEADER_MARK_H, HEADER_MARK_OUT_Y, footer_box_bottom,
                      header_mark_row_h, header_mark_top, header_mark_width)


def _mm(v: int) -> float:
    return round(v * 25.4 / 7200, 2)


def page_preview(preset: ExportPreset, layout: LayoutContext, title: str, subtitle: str) -> dict:
    """layout.summary()에 덧붙일 값. 제목이 비면 제목 상자를 넣지 않으므로 title_box_h_mm은 None이다."""
    mark = clean_text(preset.header_mark.text).strip()
    tb = title_box_spec(title, subtitle, layout) if preset.title_box.enabled else None
    return {
        "col_gap_mm": _mm(layout.col_gap),
        "title_box_h_mm": _mm(tb.parts[0].height) if tb else None,
        # 머리말 맨 위에서 표식 상자 윗변까지(top_mm), 표 아래 선까지(line_mm)
        "header_mark": {"w_mm": _mm(header_mark_width(mark, layout.body_w)), "h_mm": _mm(HEADER_MARK_H),
                        "top_mm": _mm(header_mark_top()),
                        "line_mm": _mm(HEADER_MARK_OUT_Y + header_mark_row_h())} if mark else None,
        # 쪽 번호 상자(대각선 칸): 크기, 꼬리말 맨 아래에서 상자 아랫변까지(bottom_mm, 근사값)
        "page_number_box": ({"w_mm": _mm(FOOTER_INNER_W), "h_mm": _mm(FOOTER_INNER_H), "bottom_mm": _mm(footer_box_bottom())}
                            if layout.page_number and layout.page_number_style == "box" else None),
    }
