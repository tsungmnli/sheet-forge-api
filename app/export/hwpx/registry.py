"""StyleRegistry: paraPr ID 할당과 중복 제거 (설계 7장).

템플릿의 기존 항목은 수정하지 않고 새 항목만 추가한다. ID는 템플릿의 현재 개수부터
첫 사용 순서대로 부여(결정적). tabPr(선택지)는 M3에서 추가한다.
"""
import re
from typing import NamedTuple

from .errors import TemplateError


class ParaKey(NamedTuple):
    align: str            # JUSTIFY | LEFT
    keep_with_next: bool
    keep_lines: bool
    tab_pr_id: int = 0    # M3 이전에는 템플릿의 기본 tabPr 0
    line_spacing: int = 0  # 0이면 문서 기본 줄 간격, 아니면 이 값(%)으로 고정(머리말처럼 본문 설정과 무관해야 하는 곳)


class TabKey(NamedTuple):
    line_w: int           # 줄 폭 = 단 폭
    n_cols: int


_TAB_ID_RE = re.compile(r'<hh:tabPr id="(\d+)"')
_BORDER_ID_RE = re.compile(r'<hh:borderFill id="(\d+)"')
_CHAR_ID_RE = re.compile(r'<hh:charPr id="(\d+)"')
_PARA0_RE = re.compile(r'<hh:paraPr id="0" .*?</hh:paraPr>', re.S)
_PARA_ID_RE = re.compile(r'<hh:paraPr id="(\d+)"')


def read_base_para(header_xml: str) -> str:
    m = _PARA0_RE.search(header_xml)
    if not m:
        raise TemplateError("header.xml에서 paraPr id=0을 찾지 못함")
    return m.group(0)


def next_para_id(header_xml: str) -> int:
    ids = [int(x) for x in _PARA_ID_RE.findall(header_xml)]
    if not ids:
        raise TemplateError("header.xml에 paraPr가 없음")
    return max(ids) + 1  # 개수를 하드코딩하지 않고 템플릿에서 읽는다


def _sub1(pattern: str, repl: str, text: str, count: int = 1) -> str:
    new, n = re.subn(pattern, repl, text, count=0 if count == 0 else count)
    if n == 0 or (count == 0 and n != 2):
        raise TemplateError(f"paraPr 패턴을 찾지 못함: {pattern}")
    return new


def make_para_pr(base: str, pid: int, key: ParaKey, line_spacing_pct: int) -> str:
    """paraPr id=0을 복사해 id·정렬·keep·줄 간격·탭만 바꾼다 [검증 4.5, 4.10]."""
    x = base.replace('<hh:paraPr id="0"', f'<hh:paraPr id="{pid}"', 1)
    x = _sub1(r'tabPrIDRef="\d+"', f'tabPrIDRef="{key.tab_pr_id}"', x)
    x = _sub1(r'<hh:align horizontal="\w+"', f'<hh:align horizontal="{key.align}"', x)
    x = _sub1(r'keepWithNext="\d" keepLines="\d"',
              f'keepWithNext="{int(key.keep_with_next)}" keepLines="{int(key.keep_lines)}"', x)
    # hp:case · hp:default 두 곳 모두 [검증 4.10] — 새 paraPr에 값을 넣는 것은 [제안], M1에서 확인
    x = re.sub(r'(<hh:lineSpacing type="PERCENT" value=")\d+(")', rf'\g<1>{line_spacing_pct}\2', x)
    if x.count(f'value="{line_spacing_pct}" unit="HWPUNIT"/></hp:') != 2:
        raise TemplateError("paraPr의 lineSpacing 두 곳을 찾지 못함")
    return x


class StyleRegistry:
    def __init__(self, header_xml: str, line_spacing_pct: int):
        self._base = read_base_para(header_xml)
        self._first_id = next_para_id(header_xml)
        self._line_spacing = line_spacing_pct
        self._ids: dict = {}
        self._xml: list = []
        ids = [int(x) for x in _TAB_ID_RE.findall(header_xml)]
        if not ids:
            raise TemplateError("header.xml에 tabPr가 없음")
        self._first_tab_id = max(ids) + 1
        self._tab_ids: dict = {}
        self._tab_xml: list = []
        bids = [int(x) for x in _BORDER_ID_RE.findall(header_xml)]
        if not bids:
            raise TemplateError("header.xml에 borderFill이 없음")
        self._first_border_id = max(bids) + 1
        self._border_ids: dict = {}   # 종류(table·title·slash·none) → borderFill id. 처음 쓴 순서대로 id를 준다
        cids = [int(x) for x in _CHAR_ID_RE.findall(header_xml)]
        if not cids:
            raise TemplateError("header.xml에 charPr가 없음")
        self._first_char_id = max(cids) + 1
        self._char_ids: dict = {}   # (글자 높이 HWPUNIT, 글꼴 이름 또는 None=본문 글꼴) → charPr id

    def _border(self, kind: str) -> int:
        if kind not in self._border_ids:
            self._border_ids[kind] = self._first_border_id + len(self._border_ids)
        return self._border_ids[kind]

    def table_border(self) -> int:
        """표 네 면 실선(0.12mm) borderFill. 템플릿에는 없으므로 처음 쓸 때 새로 추가한다(샘플 시험지.hwpx의 id 3과 같은 모양)."""
        return self._border("table")

    def title_border(self) -> int:
        """제목 표 칸 테두리: 아래쪽만 0.5mm 실선(sample.hwpx의 borderFill 6과 같은 모양)."""
        return self._border("title")

    def slash_border(self) -> int:
        """쪽 번호 상자 칸 테두리: 네 면 실선(0.12mm) + 대각선 `/`(sample.hwpx의 borderFill 7과 같은 모양)."""
        return self._border("slash")

    def plain_border(self) -> int:
        """테두리·채움 없음(sample.hwpx의 borderFill 5). 쪽 번호 상자를 담는 바깥 표에 쓴다."""
        return self._border("none")

    def char(self, height: int, font: "str | None" = None) -> int:
        """본문(charPr 0)을 복사해 크기(와 글꼴)만 바꾼 글자 모양. font가 None이면 본문 글꼴.
        처음 쓸 때 새로 추가한다(header_patch가 만든다)."""
        key = (height, font)
        if key not in self._char_ids:
            self._char_ids[key] = self._first_char_id + len(self._char_ids)
        return self._char_ids[key]

    @property
    def new_chars(self) -> list:
        return [(cid, h, f) for (h, f), cid in self._char_ids.items()]

    @property
    def new_border_xml(self) -> list:
        out = []   # id 순서대로
        head = 'threeD="0" shadow="0" centerLine="NONE" breakCellSeparateLine="0"'
        lines = '<hh:slash type="NONE" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
        slash = '<hh:slash type="CENTER" Crooked="0" isCounter="0"/><hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
        diag = '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>'
        solid = 'type="SOLID" width="0.12 mm" color="#000000"'
        none = 'type="NONE" width="0.1 mm" color="#000000"'
        for kind, bid in self._border_ids.items():
            if kind == "table":
                body = (f'{lines}<hh:leftBorder {solid}/><hh:rightBorder {solid}/><hh:topBorder {solid}/>'
                        f'<hh:bottomBorder {solid}/>{diag}')
            elif kind == "title":
                body = (f'{lines}<hh:leftBorder {none}/><hh:rightBorder {none}/><hh:topBorder {none}/>'
                        f'<hh:bottomBorder type="SOLID" width="0.5 mm" color="#000000"/>{diag}')
            elif kind == "slash":   # [sample.hwpx borderFill 7] 대각선도 0.12mm 실선
                body = (f'{slash}<hh:leftBorder {solid}/><hh:rightBorder {solid}/><hh:topBorder {solid}/>'
                        f'<hh:bottomBorder {solid}/><hh:diagonal type="SOLID" width="0.12 mm" color="#000000"/>')
            else:   # none
                body = (f'{lines}<hh:leftBorder {none}/><hh:rightBorder {none}/><hh:topBorder {none}/>'
                        f'<hh:bottomBorder {none}/>{diag}')
            out.append((bid, f'<hh:borderFill id="{bid}" {head}>{body}</hh:borderFill>'))
        return [x for _, x in sorted(out)]

    def tab(self, line_w: int, n_cols: int) -> int:
        """열 균등 분할 탭 정지: 위치 = round(줄 폭 × k ÷ n), k = 1…n-1 [검증 t12c, 설계 9장 4]."""
        key = TabKey(line_w, n_cols)
        if key not in self._tab_ids:
            tid = self._first_tab_id + len(self._tab_ids)
            self._tab_ids[key] = tid
            items = "".join(f'<hh:tabItem pos="{round(line_w * k / n_cols)}" type="LEFT" leader="NONE"/>'
                            for k in range(1, n_cols))
            self._tab_xml.append(f'<hh:tabPr id="{tid}" autoTabLeft="0" autoTabRight="0">{items}</hh:tabPr>')
        return self._tab_ids[key]

    @property
    def new_tab_xml(self) -> list:
        return list(self._tab_xml)

    def para(self, key: ParaKey) -> int:
        if key not in self._ids:
            pid = self._first_id + len(self._ids)
            self._ids[key] = pid
            self._xml.append(make_para_pr(self._base, pid, key, key.line_spacing or self._line_spacing))
        return self._ids[key]

    @property
    def new_para_xml(self) -> list:
        return list(self._xml)
