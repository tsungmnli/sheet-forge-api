"""section0.xml 조립 (설계 12장). 네임스페이스 선언은 재직렬화하지 않고 문자열 그대로 보존 [검증 4.2]."""
import re
from dataclasses import dataclass
from xml.sax.saxutils import escape

from .errors import TemplateError
from .box_geometry import text_em
from .builders import BoxPart, Picture, Tab, TablePart, TitlePart
from .layout import LayoutContext

PARA_ID_BASE = 2_147_483_648  # 문단 id는 카운터로 고유값 부여
TAB_XML = '<hp:tab width="0" leader="0" type="1"/>'  # 폭은 한글이 다시 계산 [검증 t11a]
PIC_ID_BASE = 1_500_000_000  # 그림 id·instid 카운터
PIC_Z_BASE = 50_000           # 그림 zOrder(수식 zOrder 0~와 겹치지 않게)
BOX_ID_BASE = 1_700_000_000   # 묶음 개체·글상자 id·instid (상자 하나가 3개씩 쓴다)
BOX_Z_BASE = 70_000           # 묶음 개체 zOrder
BOX_PARA_BASE = 3_000_000_000  # 상자 안 문단 id(본문 문단 id 2^31~ 와 겹치지 않게)
TBL_ID_BASE = 1_800_000_000   # 표 id
TBL_Z_BASE = 80_000           # 표 zOrder
BOX_UNIT = 8504               # 샘플 글상자의 orgSz(정사각). 실제 크기는 scaMatrix 배율로 정한다
EQ_ID_BASE = 1_000_000_000    # 수식 id·zOrder도 카운터로 고유값 부여 [검증 t5: 0이어도 열리지만 고유값 권장]


# 단 구분선·쪽 번호 [제안: 한글 확인 필요]. colLine은 colPr의 자식, pageNum은 colPr 뒤의 ctrl로 둔다.
COL_LINE_XML = '<hp:colLine type="SOLID" width="0.12 mm" color="#000000"/>'
PAGE_NUM_XML = '<hp:ctrl><hp:pageNum pos="BOTTOM_CENTER" formatType="DIGIT" sideChar="-"/></hp:ctrl>'

# "3 / 19" 쪽 번호: 꼬리말(양쪽 쪽) 안 가운데 문단에 쪽 번호·전체 쪽수 자동 번호를 둔다 [제안: 한글 확인 필요]
FOOTER_PARA_ID = 3_900_000_000   # 꼬리말 문단 id(본문·상자 문단 id와 겹치지 않게)
FOOTER_TBL_ID = TBL_ID_BASE - 1  # 상자 모양 쪽 번호의 바깥 표 id(안쪽 표는 -2, 본문 표 id와 겹치지 않게)

# 상자 모양 쪽 번호 [sample.hwpx 꼬리말]: 바깥 1×1 표(테두리 없음, 쪽 폭 − 좌우 바깥 여백) 안 가운데 문단에 안쪽 1×1 표
# (네 면 + 대각선 `/`)를 두고, 안쪽 칸의 문단 둘(쪽 번호 왼쪽, 전체 쪽수 오른쪽·줄간격 40%)이 겹쳐 위 왼쪽·아래 오른쪽에 놓인다.
FOOTER_PT = 1200                 # 쪽 번호 글자 12pt [sample.hwpx charPr 8]
FOOTER_OUTER_H = 3826            # 바깥 표 높이 [sample.hwpx tbl sz]
FOOTER_OUTER_OUT = 283           # 바깥 표 바깥 여백(네 면) [sample.hwpx outMargin]
FOOTER_OUTER_IN = (510, 141)     # 바깥 표 안쪽 여백(좌우, 위아래) = 칸 여백 [sample.hwpx inMargin·cellMargin]
FOOTER_INNER_W = 5032            # 안쪽 표(대각선 상자) 크기 [sample.hwpx tbl sz]
FOOTER_INNER_H = 2132
FOOTER_INNER_M = 140             # 안쪽 표 바깥·안쪽 여백(네 면) [sample.hwpx outMargin·inMargin]
FOOTER_INNER_CELL = (141, 141)   # 안쪽 칸 여백(좌우, 위아래) [sample.hwpx cellMargin]
FOOTER_OUTER_LINE_PCT = 150      # 바깥 표를 담는 문단 줄간격 [sample.hwpx paraPr 9]
FOOTER_INNER_LINE_PCT = 160      # 안쪽 표를 담는 문단 줄간격 [sample.hwpx paraPr 25]
FOOTER_NUM_LINE_PCT = 40         # 쪽 번호·전체 쪽수 문단 줄간격 [sample.hwpx paraPr 29·30]
FOOTER_CHAR_H = 1000             # 표를 담는 run의 글자 높이(charPr 0, 10pt). 줄간격 추가분 계산에 쓴다


def footer_box_bottom() -> int:
    """꼬리말 맨 아래에서 대각선 상자 아랫변까지(미리보기용 근사값) [제안: 한글 확인 필요].
    꼬리말은 아래쪽 정렬이다. 바깥 표 아래 바깥 여백 + 바깥 문단 줄간격 추가분 + 바깥 칸 아래 여백 + 칸 가운데 정렬 여유
    + 안쪽 문단 줄간격 추가분 + 안쪽 표 아래 바깥 여백."""
    inner_extra = round(FOOTER_CHAR_H * (FOOTER_INNER_LINE_PCT - 100) / 100)
    outer_extra = round(FOOTER_CHAR_H * (FOOTER_OUTER_LINE_PCT - 100) / 100)
    para_h = FOOTER_INNER_H + 2 * FOOTER_INNER_M + inner_extra
    pad = (FOOTER_OUTER_H - 2 * FOOTER_OUTER_IN[1] - para_h) // 2
    return FOOTER_OUTER_OUT + outer_extra + FOOTER_OUTER_IN[1] + pad + inner_extra + FOOTER_INNER_M


def _auto_num(num_type: str) -> str:
    return (f'<hp:ctrl><hp:autoNum num="1" numType="{num_type}"><hp:autoNumFormat type="DIGIT" userChar="" '
            'prefixChar="" suffixChar="" supscript="0"/></hp:autoNum></hp:ctrl>')


@dataclass(frozen=True)
class FooterStyle:
    """꼬리말 쪽 번호에 쓰는 스타일 id. 내보낼 때 StyleRegistry에서 받는다. para_pr는 total의 가운데 문단,
    나머지는 상자 모양(box)일 때만 쓴다."""
    para_pr: int
    border_id: int = 0       # 안쪽 표 칸 테두리(네 면 + 대각선)
    plain_id: int = 0        # 바깥 표 테두리 없음
    outer_para: int = 0      # 바깥 표를 담는 문단(가운데, 150%)
    inner_para: int = 0      # 안쪽 표를 담는 문단(가운데, 160%)
    left_para: int = 0       # 쪽 번호(왼쪽, 40%)
    right_para: int = 0      # 전체 쪽수(오른쪽, 40%)
    char_id: int = 0         # 12pt 글자 모양


def footer_need_h(enabled: bool, style: str, font_hwp: int, line_spacing_pct: int) -> int:
    """쪽 번호에 필요한 꼬리말 높이 [제안: 한글 확인 필요]. 상자는 표 높이 + 표 바깥 여백, 글자는 한 줄 높이."""
    if not enabled:
        return 0
    if style == "box":
        return FOOTER_OUTER_H + 2 * FOOTER_OUTER_OUT   # 바깥 표 + 바깥 여백(샘플 꼬리말 높이는 4251)
    return round(font_hwp * line_spacing_pct / 100)


def page_total_footer_xml(layout: LayoutContext, st: FooterStyle) -> str:
    """꼬리말 ctrl. total은 가운데 문단에 "쪽 / 전체", box는 샘플처럼 바깥 표 → 안쪽 대각선 표 → 문단 둘(쪽 번호·전체 쪽수)."""
    if layout.page_number_style == "box":
        body = _footer_box_xml(layout, st)
        para_pr = st.outer_para
    else:
        body = (f'<hp:run charPrIDRef="0">{_auto_num("PAGE")}<hp:t> / </hp:t>{_auto_num("TOTAL_PAGE")}<hp:t/></hp:run>')
        para_pr = st.para_pr
    para = (f'<hp:p id="{FOOTER_PARA_ID}" paraPrIDRef="{para_pr}" styleIDRef="0" pageBreak="0" '
            f'columnBreak="0" merged="0">{body}</hp:p>')
    return ('<hp:ctrl><hp:footer id="0" applyPageType="BOTH">'
            '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="BOTTOM" linkListIDRef="0" '
            f'linkListNextIDRef="0" textWidth="{layout.body_w}" textHeight="{layout.footer}" hasTextRef="0" '
            f'hasNumRef="0">{para}</hp:subList></hp:footer></hp:ctrl>')


def _footer_para(pid: int, para_pr: int, run: str) -> str:
    return (f'<hp:p id="{pid}" paraPrIDRef="{para_pr}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'{run}</hp:p>')


def _footer_box_xml(layout: LayoutContext, st: FooterStyle) -> str:
    """꼬리말 문단의 run. 안쪽 칸의 첫 문단은 쪽 번호(왼쪽), 둘째 문단은 전체 쪽수(오른쪽)이고 둘 다 줄간격 40%라
    겹치듯 붙어 위 왼쪽·아래 오른쪽에 놓인다. 대각선은 칸 테두리(borderFill의 slash)가 그린다. 문자 `/`는 없다."""
    def num(num_type: str) -> str:
        return f'<hp:run charPrIDRef="{st.char_id}">{_auto_num(num_type)}<hp:t/></hp:run>'

    cell = (_footer_para(FOOTER_PARA_ID + 2, st.left_para, num("PAGE"))
            + _footer_para(FOOTER_PARA_ID + 3, st.right_para, num("TOTAL_PAGE")))
    inner_t = TablePart(rows=[[None]], col_w=[FOOTER_INNER_W], row_h=[FOOTER_INNER_H], cell_pr=st.left_para,
                        border_id=st.border_id)
    inner = table_xml(FOOTER_TBL_ID - 1, TBL_Z_BASE - 2, inner_t, [[cell]], out_x=FOOTER_INNER_M, out_y=FOOTER_INNER_M,
                      in_margin=(FOOTER_INNER_M, FOOTER_INNER_M), cell_margin=FOOTER_INNER_CELL)
    outer_cell = _footer_para(FOOTER_PARA_ID + 1, st.inner_para, f'<hp:run charPrIDRef="0">{inner}<hp:t/></hp:run>')
    outer_t = TablePart(rows=[[None]], col_w=[layout.body_w - 2 * FOOTER_OUTER_OUT], row_h=[FOOTER_OUTER_H],
                        cell_pr=st.outer_para, border_id=st.plain_id)
    outer = table_xml(FOOTER_TBL_ID, TBL_Z_BASE - 1, outer_t, [[outer_cell]], out_x=FOOTER_OUTER_OUT,
                      out_y=FOOTER_OUTER_OUT, in_margin=FOOTER_OUTER_IN, cell_margin=FOOTER_OUTER_IN)
    return f'<hp:run charPrIDRef="0">{outer}<hp:t/></hp:run>'


# 머리 표식 [sample.hwpx 머리말 기준]: 쪽 폭 전체 1칸 표(칸 아래 0.5mm 선만) 안에 회색 둥근 글상자(17pt, 가운데 정렬 글).
# 위치(왼쪽·오른쪽)는 표 안 문단의 정렬로 정한다. 양면(outside)은 홀수·짝수 머리말을 따로 둔다 [제안: 한글 확인 필요]
HEADER_MARK_PT = 1700            # [sample.hwpx charPr 14]
HEADER_MARK_H = 3117             # 글상자 높이 [sample.hwpx curSz]
# 표식과 아래 선 사이 간격 [sample.hwpx 머리말]: 표 높이를 글상자보다 넉넉히(4532) 잡고, 칸 안 문단을 아래쪽 정렬(BOTTOM)로
# 둔다. 문단은 줄간격 160%라 글상자 아래에 600이 붙고, 글상자는 vertOffset 301만큼 내려가 선까지 ≈ 440(1.5mm)이 남는다.
HEADER_MARK_ROW_H = 4532         # 머리말 표 높이 [sample.hwpx tbl sz]
HEADER_MARK_LINE_PCT = 160       # 머리말 문단 줄간격(%) [sample.hwpx paraPr 26·27·32]
HEADER_PARA_SPACING = 600        # 160% 줄간격이 글상자 줄 아래에 더하는 값(본문 10pt 기준) [sample.hwpx lineseg]
HEADER_RECT_V_OFFSET = 301       # 글상자 세로 오프셋 [sample.hwpx pos]
HEADER_BODY_GAP = 1137           # 표 아래 선과 본문 사이 [sample.hwpx 머리말 높이 5669 - 표 4532]
HEADER_MARK_OUT_Y = 0            # 머리말 표 바깥 위아래 여백 [sample.hwpx outMargin]
HEADER_MARK_IN_MARGIN = (283, 566)  # 머리말 표 안쪽 여백(좌우, 위아래) [sample.hwpx inMargin]
HEADER_MARK_MIN_W = 10487        # 글상자 최소 폭 [sample.hwpx curSz]
HEADER_MARK_PAD = 1200           # 글 좌우 여백
HEADER_ID_BASE = 1_600_000_000   # 머리말 표·글상자 id(표 = +2k, 글상자 = +2k+1)
HEADER_PARA_BASE = 3_800_000_000  # 머리말 문단 id(문단 3개씩)
HEADER_TBL_Z = TBL_Z_BASE - 20   # 머리말 표 zOrder
HEADER_TBL_OUT_Y = 283           # table_xml의 표 바깥 위아래 여백
HEADER_CELL_Y = 141              # table_xml의 칸 위아래 여백


def header_mark_row_h() -> int:
    return HEADER_MARK_ROW_H


def header_mark_top() -> int:
    """머리말 맨 위에서 글상자 윗변까지. 칸 안 문단(글상자 줄 + 줄간격)이 칸 아래에 붙고 글상자는 vertOffset만큼 내려간다."""
    para_h = HEADER_MARK_H + HEADER_PARA_SPACING
    return HEADER_MARK_OUT_Y + HEADER_CELL_Y + (HEADER_MARK_ROW_H - 2 * HEADER_CELL_Y - para_h) + HEADER_RECT_V_OFFSET


def header_mark_need_h() -> int:
    """머리말 영역이 이만큼 필요하다(표 높이 + 선 아래 본문과의 간격, 샘플의 머리말 높이 5669). 쪽 여백의 머리말 높이가
    이보다 작으면 본문과 겹치거나 붙을 수 있어 plan_layout이 머리말 여백을 이 값까지 올린다."""
    return header_mark_row_h() + 2 * HEADER_MARK_OUT_Y + HEADER_BODY_GAP


def header_mark_width(text: str, body_w: int) -> int:
    return min(max(HEADER_MARK_MIN_W, round(text_em(text) * HEADER_MARK_PT) + 2 * HEADER_MARK_PAD), body_w // 2)


@dataclass(frozen=True)
class HeaderMarkStyle:
    """머리 표식에 쓰는 스타일 id. 내보낼 때 StyleRegistry에서 받는다."""
    text: str
    para_left: int     # 왼쪽 정렬 문단 모양
    para_right: int    # 오른쪽 정렬 문단 모양
    para_center: int   # 글상자 안 글: 가운데 정렬
    border_id: int     # 칸 아래 선만 있는 테두리
    char_id: int       # 17pt 글자 모양


def _header_rect_xml(rect_id: int, w: int, h: int, para: str) -> str:
    """회색 둥근 글상자(ratio 50, 채움 #F1F1F1, 선 56) — 글자처럼 취급. 크기 표현은 plain_box_xml과 같다."""
    ident = 'e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"'
    return (f'<hp:rect id="{rect_id}" zOrder="{HEADER_TBL_Z + 1}" numberingType="PICTURE" textWrap="IN_FRONT_OF_TEXT" '
            f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{rect_id}" ratio="50">'
            f'<hp:offset x="0" y="0"/><hp:orgSz width="{BOX_UNIT}" height="{BOX_UNIT}"/><hp:curSz width="{w}" height="{h}"/>'
            '<hp:flip horizontal="0" vertical="0"/>'
            f'<hp:rotationInfo angle="0" centerX="{w // 2}" centerY="{h // 2}" rotateimage="1"/>'
            f'<hp:renderingInfo><hc:transMatrix {ident}/>'
            f'<hc:scaMatrix e1="{_f(w / BOX_UNIT)}" e2="0" e3="0" e4="0" e5="{_f(h / BOX_UNIT)}" e6="0"/>'
            f'<hc:rotMatrix {ident}/></hp:renderingInfo>'
            '<hp:lineShape color="#000000" width="56" style="SOLID" endCap="FLAT" headStyle="NORMAL" tailStyle="NORMAL" '
            'headfill="1" tailfill="1" headSz="SMALL_SMALL" tailSz="SMALL_SMALL" outlineStyle="NORMAL" alpha="0"/>'
            '<hc:fillBrush><hc:winBrush faceColor="#F1F1F1" hatchColor="#000000" alpha="0"/></hc:fillBrush>'
            '<hp:shadow type="NONE" color="#000000" offsetX="0" offsetY="0" alpha="0"/>'
            f'<hp:drawText lastWidth="{w}" name="" editable="0">'
            '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" '
            'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'{para}</hp:subList><hp:textMargin left="283" right="283" top="283" bottom="283"/></hp:drawText>'
            f'<hc:pt0 x="0" y="0"/><hc:pt1 x="{BOX_UNIT}" y="0"/><hc:pt2 x="{BOX_UNIT}" y="{BOX_UNIT}"/>'
            f'<hc:pt3 x="0" y="{BOX_UNIT}"/>'
            f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            f'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="{HEADER_RECT_V_OFFSET}" '
            'horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:shapeComment>사각형입니다.</hp:shapeComment>'
            '</hp:rect>')


def _one_header_xml(k: int, apply_type: str, side: str, layout: LayoutContext, st: HeaderMarkStyle) -> str:
    """머리말 ctrl 하나. side: left | right(표 안 글상자가 놓이는 쪽)."""
    w = header_mark_width(st.text, layout.body_w)
    base_p = HEADER_PARA_BASE + 10 * k
    inner = paragraph_xml(base_p + 2, st.para_center, [st.text], None, char_pr=st.char_id)
    rect = _header_rect_xml(HEADER_ID_BASE + 2 * k + 1, w, HEADER_MARK_H, inner)
    cell = (f'<hp:p id="{base_p + 1}" paraPrIDRef="{st.para_right if side == "right" else st.para_left}" styleIDRef="0" '
            f'pageBreak="0" columnBreak="0" merged="0"><hp:run charPrIDRef="0">{rect}<hp:t/></hp:run></hp:p>')
    t = TablePart(rows=[[None]], col_w=[layout.body_w], row_h=[header_mark_row_h()], cell_pr=st.para_left,
                  border_id=st.border_id)
    tbl = table_xml(HEADER_ID_BASE + 2 * k, HEADER_TBL_Z, t, [[cell]], v_align="BOTTOM", out_y=HEADER_MARK_OUT_Y,
                    in_margin=HEADER_MARK_IN_MARGIN)
    para = (f'<hp:p id="{base_p}" paraPrIDRef="{st.para_left}" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="0">{tbl}<hp:t/></hp:run></hp:p>')
    return (f'<hp:ctrl><hp:header id="{k + 1}" applyPageType="{apply_type}">'
            '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="TOP" linkListIDRef="0" '
            f'linkListNextIDRef="0" textWidth="{layout.body_w}" textHeight="{layout.header}" hasTextRef="0" '
            f'hasNumRef="0">{para}</hp:subList></hp:header></hp:ctrl>')


def header_mark_xml(layout: LayoutContext, st: HeaderMarkStyle) -> str:
    """left·right는 모든 쪽에 같은 머리말 하나, outside는 홀수 쪽(오른쪽)·짝수 쪽(왼쪽) 머리말 둘."""
    pos = layout.header_mark_position
    if pos == "outside":
        return (_one_header_xml(0, "ODD", "right", layout, st) + _one_header_xml(1, "EVEN", "left", layout, st))
    return _one_header_xml(0, "BOTH", "left" if pos == "left" else "right", layout, st)


def _need1(pattern: str, repl: str, text: str) -> str:
    new, n = re.subn(pattern, lambda _m: repl, text, count=1)
    if n != 1:
        raise TemplateError(f"section0.xml 패턴을 찾지 못함: {pattern}")
    return new


def equation_xml(eq_id: int, z_order: int, script: str, base_unit: int) -> str:
    """수식 최소형 [검증 4.3 t6a]: sz·baseLine은 모두 0(한글이 열 때 계산), linesegarray 없음,
    baseUnit은 본문 글자 크기와 같게 [검증 t17a]."""
    return (f'<hp:equation id="{eq_id}" zOrder="{z_order}" numberingType="EQUATION" textWrap="TOP_AND_BOTTOM" '
            f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" version="Equation Version 60" baseLine="0" '
            f'textColor="#000000" baseUnit="{base_unit}" lineMode="CHAR" font="HancomEQN">'
            '<hp:sz width="0" widthRelTo="ABSOLUTE" height="0" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="56" right="56" top="0" bottom="0"/>'
            '<hp:shapeComment>수식입니다.</hp:shapeComment>'
            f'<hp:script>{escape(script)}</hp:script></hp:equation>')


def picture_xml(pic_id: int, z_order: int, bin_id: int, w: int, h: int, org_w: int = 0, org_h: int = 0) -> str:
    """hp:pic 최소형 [검증 4.7.2 t15a]. orgSz = curSz = sz, scaMatrix 항등.
    imgClip은 이미지 원본 크기 기준이다(줄인 그림에서 표시 크기를 쓰면 일부만 확대되어 보인다) [검증 2026-11-17]."""
    cw = org_w or w
    ch = org_h or h
    return (f'<hp:pic id="{pic_id}" zOrder="{z_order}" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM" '
            f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{pic_id}" reverse="0">'
            f'<hp:orgSz width="{w}" height="{h}"/><hp:curSz width="{w}" height="{h}"/>'
            '<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
            '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
            '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
            f'<hc:img binaryItemIDRef="image{bin_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
            f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{w}" y="0"/><hc:pt2 x="{w}" y="{h}"/><hc:pt3 x="0" y="{h}"/></hp:imgRect>'
            f'<hp:imgClip left="0" right="{cw}" top="0" bottom="{ch}"/>'
            f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:shapeComment>그림입니다.</hp:shapeComment></hp:pic>')


def _f(v: float) -> str:
    return f"{v:.6f}".rstrip("0").rstrip(".")


def _rect_xml(inst: int, x: int, y: int, w: int, h: int, solid: bool, last_w: int, paras: str) -> str:
    """글상자 하나(hp:rect + drawText). 샘플의 모양을 그대로 따른다: orgSz는 8504 정사각형,
    크기는 두 번째 scaMatrix 배율(w/8504, h/8504), 위치는 offset과 transMatrix 둘 다에 넣는다."""
    line = ('<hp:lineShape color="#000000" width="33" style="SOLID" endCap="FLAT" headStyle="NORMAL" tailStyle="NORMAL" '
            'headfill="1" tailfill="1" headSz="MEDIUM_MEDIUM" tailSz="MEDIUM_MEDIUM" outlineStyle="NORMAL" alpha="0"/>'
            if solid else
            '<hp:lineShape color="#000000" width="33" style="NONE" endCap="FLAT" headStyle="NORMAL" tailStyle="NORMAL" '
            'headfill="1" tailfill="1" headSz="SMALL_SMALL" tailSz="SMALL_SMALL" outlineStyle="NORMAL" alpha="0"/>')
    ident = 'e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"'
    return (f'<hp:rect id="0" zOrder="0" numberingType="NONE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
            f'dropcapstyle="None" href="" groupLevel="1" instid="{inst}" ratio="0">'
            f'<hp:offset x="{x}" y="{y}"/><hp:orgSz width="{BOX_UNIT}" height="{BOX_UNIT}"/><hp:curSz width="0" height="0"/>'
            '<hp:flip horizontal="0" vertical="0"/>'
            f'<hp:rotationInfo angle="0" centerX="{w // 2}" centerY="{h // 2}" rotateimage="1"/>'
            f'<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="{x}" e4="0" e5="1" e6="{y}"/>'
            f'<hc:scaMatrix {ident}/><hc:rotMatrix {ident}/>'
            f'<hc:scaMatrix e1="{_f(w / BOX_UNIT)}" e2="0" e3="0" e4="0" e5="{_f(h / BOX_UNIT)}" e6="0"/>'
            f'<hc:rotMatrix {ident}/></hp:renderingInfo>'
            f'{line}'
            '<hc:fillBrush><hc:winBrush faceColor="#FFFFFF" hatchColor="#000000" alpha="0"/></hc:fillBrush>'
            '<hp:shadow type="NONE" color="#B2B2B2" offsetX="0" offsetY="0" alpha="0"/>'
            f'<hp:drawText lastWidth="{last_w}" name="" editable="0">'
            '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" '
            'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'{paras}</hp:subList><hp:textMargin left="283" right="283" top="283" bottom="283"/></hp:drawText>'
            f'<hc:pt0 x="0" y="0"/><hc:pt1 x="{BOX_UNIT}" y="0"/><hc:pt2 x="{BOX_UNIT}" y="{BOX_UNIT}"/>'
            f'<hc:pt3 x="0" y="{BOX_UNIT}"/></hp:rect>')


def box_xml(base_id: int, z_order: int, geom, body_paras: str, title_para: str) -> str:
    """<보기> 묶음 개체. 본문 글상자(테두리 있음)를 title_h/2만큼 내리고, 그 위 빈 자리에 제목 글상자(테두리 없음,
    흰 배경)를 가로 가운데로 얹어 윗선이 제목 뒤로 끊겨 보이게 한다. 샘플과 다른 점은 위치 기준뿐이다:
    쪽 기준 절대좌표(PAPER) 대신 문단 기준·글자처럼 취급(PARA)이라 문항 순서가 바뀌어도 따라간다 [제안: 한글 확인 필요]."""
    w, h = geom.width, geom.height
    ident = 'e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"'
    body = _rect_xml(base_id + 1, 0, geom.body_y, w, geom.body_h, True, w, body_paras)
    title = _rect_xml(base_id + 2, geom.title_x, 0, geom.title_w, geom.title_h, False, geom.title_w, title_para)
    return (f'<hp:container id="{base_id}" zOrder="{z_order}" numberingType="PICTURE" textWrap="IN_FRONT_OF_TEXT" '
            f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{base_id}">'
            f'<hp:offset x="0" y="0"/><hp:orgSz width="{w}" height="{h}"/><hp:curSz width="0" height="0"/>'
            '<hp:flip horizontal="0" vertical="0"/>'
            f'<hp:rotationInfo angle="0" centerX="{w // 2}" centerY="{h // 2}" rotateimage="1"/>'
            f'<hp:renderingInfo><hc:transMatrix {ident}/><hc:scaMatrix {ident}/><hc:rotMatrix {ident}/></hp:renderingInfo>'
            f'{body}{title}'
            f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="0" allowOverlap="1" holdAnchorAndSO="0" '
            'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:shapeComment>묶음 개체입니다.</hp:shapeComment>'
            '</hp:container>')


def plain_box_xml(base_id: int, z_order: int, geom, body_paras: str) -> str:
    """제목 없는 상자: 묶음 개체 없이 hp:rect 하나(샘플 시험지.hwpx의 조건 상자와 같은 모양).
    orgSz는 8504 정사각형, 크기는 curSz와 scaMatrix 배율(w/8504, h/8504). 위치는 샘플의 쪽 기준이 아니라
    문단 기준·글자처럼 취급(PARA)이라 문항 순서가 바뀌어도 따라간다(vertOffset 932는 제목 자리였으므로 0) [제안: 한글 확인 필요]."""
    w, h = geom.width, geom.height
    ident = 'e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"'
    return (f'<hp:rect id="{base_id}" zOrder="{z_order}" numberingType="PICTURE" textWrap="IN_FRONT_OF_TEXT" '
            f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{base_id}" ratio="0">'
            f'<hp:offset x="0" y="0"/><hp:orgSz width="{BOX_UNIT}" height="{BOX_UNIT}"/><hp:curSz width="{w}" height="{h}"/>'
            '<hp:flip horizontal="0" vertical="0"/>'
            f'<hp:rotationInfo angle="0" centerX="{w // 2}" centerY="{h // 2}" rotateimage="1"/>'
            f'<hp:renderingInfo><hc:transMatrix {ident}/>'
            f'<hc:scaMatrix e1="{_f(w / BOX_UNIT)}" e2="0" e3="0" e4="0" e5="{_f(h / BOX_UNIT)}" e6="0"/>'
            f'<hc:rotMatrix {ident}/></hp:renderingInfo>'
            '<hp:lineShape color="#000000" width="33" style="SOLID" endCap="FLAT" headStyle="NORMAL" tailStyle="NORMAL" '
            'headfill="1" tailfill="1" headSz="MEDIUM_MEDIUM" tailSz="MEDIUM_MEDIUM" outlineStyle="NORMAL" alpha="0"/>'
            '<hc:fillBrush><hc:winBrush faceColor="#FFFFFF" hatchColor="#000000" alpha="0"/></hc:fillBrush>'
            '<hp:shadow type="NONE" color="#B2B2B2" offsetX="0" offsetY="0" alpha="0"/>'
            f'<hp:drawText lastWidth="{w}" name="" editable="0">'
            '<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" '
            'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">'
            f'{body_paras}</hp:subList><hp:textMargin left="283" right="283" top="283" bottom="283"/></hp:drawText>'
            f'<hc:pt0 x="0" y="0"/><hc:pt1 x="{BOX_UNIT}" y="0"/><hc:pt2 x="{BOX_UNIT}" y="{BOX_UNIT}"/>'
            f'<hc:pt3 x="0" y="{BOX_UNIT}"/>'
            f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="0" allowOverlap="1" holdAnchorAndSO="0" '
            'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:shapeComment>사각형입니다.</hp:shapeComment>'
            '</hp:rect>')


def table_xml(tbl_id: int, z_order: int, t: TablePart, cells: list, v_align: str = "CENTER", out_y: int = 283,
              in_margin: tuple = (510, 141), out_x: int = 0, cell_margin: tuple = (510, 141)) -> str:
    """표. 샘플(시험지.hwpx)의 hp:tbl 모양을 따르되 위치는 글자처럼 취급(PARA)·쪽 나눔 없음이다 [제안: 한글 확인 필요].
    cells[r][c]는 칸 안 문단 XML. 칸 크기는 최소값이고 한글이 내용에 맞춰 행 높이를 늘린다.
    v_align: 칸 안 세로 정렬, out_x·out_y: 표 바깥 좌우·위아래 여백, in_margin: 표 안쪽 여백(좌우, 위아래),
    cell_margin: 칸 여백(좌우, 위아래). 기본값은 본문 표의 값."""
    bid = t.border_id
    rows = []
    for r, row in enumerate(cells):
        tcs = []
        for c, para in enumerate(row):
            tcs.append(
                f'<hp:tc name="" header="0" hasMargin="0" protect="0" editable="0" dirty="0" borderFillIDRef="{bid}">'
                f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="{v_align}" linkListIDRef="0" '
                f'linkListNextIDRef="0" textWidth="0" textHeight="0" hasTextRef="0" hasNumRef="0">{para}</hp:subList>'
                f'<hp:cellAddr colAddr="{c}" rowAddr="{r}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
                f'<hp:cellSz width="{t.col_w[c]}" height="{t.row_h[r]}"/>'
                f'<hp:cellMargin left="{cell_margin[0]}" right="{cell_margin[0]}" top="{cell_margin[1]}" '
                f'bottom="{cell_margin[1]}"/></hp:tc>')
        rows.append(f'<hp:tr>{"".join(tcs)}</hp:tr>')
    return (f'<hp:tbl id="{tbl_id}" zOrder="{z_order}" numberingType="TABLE" textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" '
            f'lock="0" dropcapstyle="None" pageBreak="NONE" repeatHeader="0" rowCnt="{len(t.rows)}" colCnt="{len(t.col_w)}" '
            f'cellSpacing="0" borderFillIDRef="{bid}" noAdjust="0">'
            f'<hp:sz width="{t.width}" widthRelTo="ABSOLUTE" height="{t.height}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            f'<hp:outMargin left="{out_x}" right="{out_x}" top="{out_y}" bottom="{out_y}"/>'
            f'<hp:inMargin left="{in_margin[0]}" right="{in_margin[0]}" top="{in_margin[1]}" bottom="{in_margin[1]}"/>'
            f'{"".join(rows)}</hp:tbl>')


class _Ctx:
    """문서 순서대로 수식 id·zOrder를 부여한다(같은 입력 → 같은 바이트)."""

    def __init__(self, base_unit: int):
        self.base_unit = base_unit
        self.n_eq = 0
        self.n_pic = 0
        self.n_box = 0
        self.n_ipara = 0
        self.n_tbl = 0

    def table(self, t: TablePart) -> str:
        n = self.n_tbl
        self.n_tbl += 1

        def para(parts):
            self.n_ipara += 1
            return paragraph_xml(BOX_PARA_BASE + self.n_ipara, t.cell_pr, parts, self)

        cells = [[para(parts) for parts in row] for row in t.rows]
        return table_xml(TBL_ID_BASE + n, TBL_Z_BASE + n, t, cells)

    def title_table(self, t: TitlePart) -> str:
        n = self.n_tbl
        self.n_tbl += 1
        paras = []
        lines = [(t.title, t.title_char)] + ([(t.subtitle, t.sub_char)] if t.subtitle else [])
        for text, char in lines:
            self.n_ipara += 1
            paras.append(paragraph_xml(BOX_PARA_BASE + self.n_ipara, t.para_pr, [text], self, char_pr=char))
        return table_xml(TBL_ID_BASE + n, TBL_Z_BASE + n,
                         TablePart([[""]], [t.width], [t.height], t.para_pr, t.border_id), [["".join(paras)]])

    def box(self, b: BoxPart) -> str:
        n = self.n_box
        self.n_box += 1

        def para(pr, parts):
            self.n_ipara += 1
            return paragraph_xml(BOX_PARA_BASE + self.n_ipara, pr, parts, self)

        body = "".join(para(b.body_pr, parts) for parts in b.lines)
        if not b.title:   # 제목 없는 상자: 글상자 하나. id는 묶음 개체와 같은 번호 칸(3개씩)을 쓴다
            return plain_box_xml(BOX_ID_BASE + 3 * n, BOX_Z_BASE + n, b.geom, body)
        return box_xml(BOX_ID_BASE + 3 * n, BOX_Z_BASE + n, b.geom, body, para(b.title_pr, [b.title]))

    def picture(self, p: Picture) -> str:
        n = self.n_pic
        self.n_pic += 1
        return picture_xml(PIC_ID_BASE + n, PIC_Z_BASE + n, p.bin_id, p.width, p.height, p.org_w, p.org_h)

    def equation(self, script: str) -> str:
        n = self.n_eq
        self.n_eq += 1
        return equation_xml(EQ_ID_BASE + n, n, script, self.base_unit)


def _runs(parts, ctx: "_Ctx", char_pr: int = 0) -> str:
    """parts: str | list[str | Equation]. 한 run 안에 글자·수식을 순서대로 넣고,
    수식 뒤에 글자가 이어지지 않으면 빈 <hp:t/>를 둔다(README 4.3 샘플의 모양) [제안: 한글 확인 필요]."""
    if isinstance(parts, str):
        parts = [parts] if parts else []
    items, buf = [], None
    for k, p in enumerate(parts):
        if isinstance(p, (str, Tab)):   # 글자와 탭은 한 <hp:t> 안에 둔다 [README 4.2]
            buf = (buf or "") + (escape(p) if isinstance(p, str) else TAB_XML)
            continue
        if buf is not None:
            items.append(f"<hp:t>{buf}</hp:t>")
            buf = None
        items.append(ctx.picture(p) if isinstance(p, Picture) else ctx.box(p) if isinstance(p, BoxPart)
                     else ctx.title_table(p) if isinstance(p, TitlePart) else ctx.table(p) if isinstance(p, TablePart) else ctx.equation(p.script))
        if k + 1 >= len(parts) or not isinstance(parts[k + 1], (str, Tab)):
            items.append("<hp:t/>")
    if buf is not None:
        items.append(f"<hp:t>{buf}</hp:t>")
    inner = "".join(items) or "<hp:t/>"
    return f'<hp:run charPrIDRef="{char_pr}">{inner}</hp:run>'


def paragraph_xml(pid_attr: int, para_pr_id: int, parts, ctx: "_Ctx | None" = None, prefix: str = "",
                  char_pr: int = 0) -> str:
    ctx = ctx or _Ctx(1000)
    return (f'<hp:p id="{pid_attr}" paraPrIDRef="{para_pr_id}" styleIDRef="0" pageBreak="0" '
            f'columnBreak="0" merged="0">{prefix}{_runs(parts, ctx, char_pr)}</hp:p>')


def render_section(template_xml: str, layout: LayoutContext, paragraphs: list,
                   footer: "FooterStyle | None" = None, title_table: bool = False,
                   header_mark: "HeaderMarkStyle | None" = None) -> str:
    """paragraphs: [(para_pr_id, parts), ...] (parts: str 또는 str|Equation 리스트).
    첫 항목은 템플릿 첫 문단(secPr·colPr run)에 합쳐 방출 [제안]."""
    if not paragraphs:
        raise TemplateError("문단이 없음")
    start = template_xml.find("<hp:p ")
    cut = template_xml.find("</hp:ctrl></hp:run>")
    if start < 0 or cut < 0:
        raise TemplateError("템플릿 첫 문단 구조를 찾지 못함")
    cut += len("</hp:ctrl></hp:run>")
    head, first_open_end = template_xml[:start], template_xml.find(">", start) + 1
    first_tag = template_xml[start:first_open_end]
    secpr_run = template_xml[first_open_end:cut]

    # 쪽 설정·단 치환: 속성만 바꾸고 나머지는 그대로 [검증 4.9, 4.4]
    secpr_run = _need1(
        r'<hp:pagePr [^>]*>',
        f'<hp:pagePr landscape="{layout.landscape_attr}" width="{layout.page_w}" height="{layout.page_h}" '
        f'gutterType="LEFT_ONLY">', secpr_run)
    secpr_run = _need1(
        r'<hp:margin [^>]*/>',
        f'<hp:margin header="{layout.header}" footer="{layout.footer}" gutter="{layout.gutter}" '
        f'left="{layout.left}" right="{layout.right}" top="{layout.top}" bottom="{layout.bottom}"/>', secpr_run)
    col_pr = (f'<hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="{layout.col_count}" sameSz="1" '
              f'sameGap="{layout.col_gap}"')
    col_pr += f'>{COL_LINE_XML}</hp:colPr>' if layout.col_divider else '/>'
    col_start = ""
    if title_table and layout.col_count > 1:
        # [sample.hwpx] 제목 표는 1단 구역에 두고, 다음 문단 맨 앞(별도 run)에서 단 설정을 나눈다
        col_start = f'<hp:run charPrIDRef="0"><hp:ctrl>{col_pr}</hp:ctrl></hp:run>'
        col_pr = '<hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="1" sameSz="1" sameGap="0"/>'
    secpr_run = _need1(r'<hp:colPr [^>]*/>', col_pr, secpr_run)
    if layout.page_number:   # 쪽 번호는 쪽 설정과 같은 첫 문단의 run 끝에 둔다
        if layout.page_number_style == "dash":
            num_xml = PAGE_NUM_XML
        else:
            if footer is None:
                raise TemplateError("꼬리말 쪽 번호 스타일이 없음")
            num_xml = page_total_footer_xml(layout, footer)
        secpr_run = _need1(r'</hp:ctrl></hp:run>$', f'</hp:ctrl>{num_xml}</hp:run>', secpr_run)
    if header_mark is not None:   # 머리 표식: 쪽 설정과 같은 첫 문단의 run 끝에 머리말을 둔다
        secpr_run = _need1(r'</hp:ctrl></hp:run>$', f'</hp:ctrl>{header_mark_xml(layout, header_mark)}</hp:run>',
                           secpr_run)
        if title_table:   # 첫 쪽에 제목 상자가 있으면 첫 쪽 머리말은 숨긴다(둘째 쪽부터 보인다)
            secpr_run = _need1(r'hideFirstHeader="0"', 'hideFirstHeader="1"', secpr_run)

    ctx = _Ctx(layout.eq_font_hwp)
    first_pr, first_parts = paragraphs[0]
    first_tag = _need1(r'paraPrIDRef="\d+"', f'paraPrIDRef="{first_pr}"', first_tag)
    first_tag = _need1(r' id="\d+"', f' id="{PARA_ID_BASE}"', first_tag)
    out = [head, first_tag, secpr_run, _runs(first_parts, ctx), "</hp:p>"]
    for n, (pr, parts) in enumerate(paragraphs[1:], start=1):
        out.append(paragraph_xml(PARA_ID_BASE + n, pr, parts, ctx, col_start if n == 1 else ""))
    out.append("</hs:sec>")
    return "".join(out)
