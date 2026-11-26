"""header.xml 패치: charPr 0 글꼴·크기, fontfaces 추가, paraPr 추가, 개수 갱신 (설계 2장 header_patch)."""
import re
from xml.sax.saxutils import quoteattr

from .errors import TemplateError
from .layout import LayoutContext
from .registry import StyleRegistry

# 글자 종류별 글꼴 칸 전부(hh:fontRef 속성 순서). 일부만 바꾸면 기호·한자 등이 템플릿 글꼴로 남는다.
# HANGUL·LATIN은 [검증 t17b], 나머지는 [제안: 한글 확인 필요]
_FONT_LANGS = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")


def _fontface_span(xml: str, lang: str):
    m = re.search(rf'<hh:fontface lang="{lang}" fontCnt="(\d+)">(.*?)</hh:fontface>', xml, re.S)
    if not m:
        raise TemplateError(f"fontface {lang}을 찾지 못함")
    return m


def _ensure_font(xml: str, lang: str, face: str):
    """(새 xml, 글꼴 id). 같은 이름이 있으면 재사용하고, 없으면 새 id로 추가(fontCnt 갱신)."""
    m = _fontface_span(xml, lang)
    body = m.group(2)
    for fm in re.finditer(r'<hh:font id="(\d+)" face="([^"]*)"', body):
        if fm.group(2) == face:
            return xml, int(fm.group(1))
    ids = [int(x) for x in re.findall(r'<hh:font id="(\d+)"', body)]
    new_id = max(ids) + 1 if ids else 0
    font = (f'<hh:font id="{new_id}" face={quoteattr(face)} type="TTF" isEmbedded="0">'
            '<hh:typeInfo familyType="FCAT_GOTHIC" weight="6" proportion="4" contrast="0" '
            'strokeVariation="1" armStyle="1" letterform="1" midline="1" xHeight="1"/></hh:font>')
    new = f'<hh:fontface lang="{lang}" fontCnt="{len(ids) + 1}">{body}{font}</hh:fontface>'
    return xml[:m.start()] + new + xml[m.end():], new_id


def patch_header(header_xml: str, layout: LayoutContext, font_name: str, registry: StyleRegistry) -> str:
    xml = header_xml
    # 1) 글꼴
    font_ids = {}
    for lang in _FONT_LANGS:
        xml, font_ids[lang] = _ensure_font(xml, lang, font_name)
    # 2) charPr 0: 크기 + fontRef [검증 t17a, t17b]
    m = re.search(r'<hh:charPr id="0" .*?</hh:charPr>', xml, re.S)
    if not m:
        raise TemplateError("charPr id=0을 찾지 못함")
    c = m.group(0)
    c = re.sub(r'(<hh:charPr id="0" height=")\d+(")', rf'\g<1>{layout.font_hwp}\2', c, count=1)
    refs = " ".join(f'{lang.lower()}="{font_ids[lang]}"' for lang in _FONT_LANGS)
    c, n = re.subn(r'<hh:fontRef [^>]*/>', f'<hh:fontRef {refs}/>', c, count=1)
    if n != 1:
        raise TemplateError("charPr 0의 fontRef를 찾지 못함")
    xml = xml[:m.start()] + c + xml[m.end():]
    # 3) paraPr 추가 + itemCnt 갱신 [검증 4.5]
    new = registry.new_para_xml
    if new:
        pm = re.search(r'<hh:paraProperties itemCnt="(\d+)">', xml)
        if not pm or "</hh:paraProperties>" not in xml:
            raise TemplateError("paraProperties를 찾지 못함")
        cnt = int(pm.group(1)) + len(new)
        xml = xml.replace(pm.group(0), f'<hh:paraProperties itemCnt="{cnt}">', 1)
        xml = xml.replace("</hh:paraProperties>", "".join(new) + "</hh:paraProperties>", 1)
    # 4) tabPr 추가 + itemCnt 갱신 [검증 4.7.1]
    tabs = registry.new_tab_xml
    if tabs:
        tm = re.search(r'<hh:tabProperties itemCnt="(\d+)">', xml)
        if not tm or "</hh:tabProperties>" not in xml:
            raise TemplateError("tabProperties를 찾지 못함")
        xml = xml.replace(tm.group(0), f'<hh:tabProperties itemCnt="{int(tm.group(1)) + len(tabs)}">', 1)
        xml = xml.replace("</hh:tabProperties>", "".join(tabs) + "</hh:tabProperties>", 1)
    # 5) borderFill 추가 + itemCnt 갱신 (표 테두리)
    borders = registry.new_border_xml
    if borders:
        bm = re.search(r'<hh:borderFills itemCnt="(\d+)">', xml)
        if not bm or "</hh:borderFills>" not in xml:
            raise TemplateError("borderFills를 찾지 못함")
        xml = xml.replace(bm.group(0), f'<hh:borderFills itemCnt="{int(bm.group(1)) + len(borders)}">', 1)
        xml = xml.replace("</hh:borderFills>", "".join(borders) + "</hh:borderFills>", 1)
    return xml
