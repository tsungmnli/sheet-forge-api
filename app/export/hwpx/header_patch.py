"""header.xml 패치: charPr 0 글꼴·크기, fontfaces 추가, paraPr 추가, 개수 갱신 (설계 2장 header_patch)."""
import re
from xml.sax.saxutils import quoteattr

from .errors import TemplateError
from .layout import LayoutContext
from .registry import StyleRegistry

_FONT_LANGS = ("HANGUL", "LATIN")  # [검증 t17b]


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
    c, n = re.subn(r'<hh:fontRef hangul="\d+" latin="(\d+)"',
                   f'<hh:fontRef hangul="{font_ids["HANGUL"]}" latin="{font_ids["LATIN"]}"', c, count=1)
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
    return xml
