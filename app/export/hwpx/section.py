"""section0.xml 조립 (설계 12장). 네임스페이스 선언은 재직렬화하지 않고 문자열 그대로 보존 [검증 4.2]."""
import re
from xml.sax.saxutils import escape

from .errors import TemplateError
from .builders import Picture, Tab
from .layout import LayoutContext

PARA_ID_BASE = 2_147_483_648  # 문단 id는 카운터로 고유값 부여
TAB_XML = '<hp:tab width="0" leader="0" type="1"/>'  # 폭은 한글이 다시 계산 [검증 t11a]
PIC_ID_BASE = 1_500_000_000  # 그림 id·instid 카운터
PIC_Z_BASE = 50_000           # 그림 zOrder(수식 zOrder 0~와 겹치지 않게)
EQ_ID_BASE = 1_000_000_000    # 수식 id·zOrder도 카운터로 고유값 부여 [검증 t5: 0이어도 열리지만 고유값 권장]


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


def picture_xml(pic_id: int, z_order: int, bin_id: int, w: int, h: int) -> str:
    """hp:pic 최소형 [검증 4.7.2 t15a]. orgSz = curSz = sz, scaMatrix 항등, imgRect·imgClip은 org 기준."""
    return (f'<hp:pic id="{pic_id}" zOrder="{z_order}" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM" '
            f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{pic_id}" reverse="0">'
            f'<hp:orgSz width="{w}" height="{h}"/><hp:curSz width="{w}" height="{h}"/>'
            '<hp:renderingInfo><hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
            '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
            '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/></hp:renderingInfo>'
            f'<hc:img binaryItemIDRef="image{bin_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
            f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{w}" y="0"/><hc:pt2 x="{w}" y="{h}"/><hc:pt3 x="0" y="{h}"/></hp:imgRect>'
            f'<hp:imgClip left="0" right="{w}" top="0" bottom="{h}"/>'
            f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" '
            'vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:shapeComment>그림입니다.</hp:shapeComment></hp:pic>')


class _Ctx:
    """문서 순서대로 수식 id·zOrder를 부여한다(같은 입력 → 같은 바이트)."""

    def __init__(self, base_unit: int):
        self.base_unit = base_unit
        self.n_eq = 0
        self.n_pic = 0

    def picture(self, p: Picture) -> str:
        n = self.n_pic
        self.n_pic += 1
        return picture_xml(PIC_ID_BASE + n, PIC_Z_BASE + n, p.bin_id, p.width, p.height)

    def equation(self, script: str) -> str:
        n = self.n_eq
        self.n_eq += 1
        return equation_xml(EQ_ID_BASE + n, n, script, self.base_unit)


def _runs(parts, ctx: "_Ctx") -> str:
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
        items.append(ctx.picture(p) if isinstance(p, Picture) else ctx.equation(p.script))
        if k + 1 >= len(parts) or not isinstance(parts[k + 1], (str, Tab)):
            items.append("<hp:t/>")
    if buf is not None:
        items.append(f"<hp:t>{buf}</hp:t>")
    inner = "".join(items) or "<hp:t/>"
    return f'<hp:run charPrIDRef="0">{inner}</hp:run>'


def paragraph_xml(pid_attr: int, para_pr_id: int, parts, ctx: "_Ctx | None" = None) -> str:
    ctx = ctx or _Ctx(1000)
    return (f'<hp:p id="{pid_attr}" paraPrIDRef="{para_pr_id}" styleIDRef="0" pageBreak="0" '
            f'columnBreak="0" merged="0">{_runs(parts, ctx)}</hp:p>')


def render_section(template_xml: str, layout: LayoutContext, paragraphs: list) -> str:
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
    secpr_run = _need1(
        r'<hp:colPr [^>]*/>',
        f'<hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="{layout.col_count}" sameSz="1" '
        f'sameGap="{layout.col_gap}"/>', secpr_run)

    ctx = _Ctx(layout.font_hwp)
    first_pr, first_parts = paragraphs[0]
    first_tag = _need1(r'paraPrIDRef="\d+"', f'paraPrIDRef="{first_pr}"', first_tag)
    first_tag = _need1(r' id="\d+"', f' id="{PARA_ID_BASE}"', first_tag)
    out = [head, first_tag, secpr_run, _runs(first_parts, ctx), "</hp:p>"]
    for n, (pr, parts) in enumerate(paragraphs[1:], start=1):
        out.append(paragraph_xml(PARA_ID_BASE + n, pr, parts, ctx))
    out.append("</hs:sec>")
    return "".join(out)
