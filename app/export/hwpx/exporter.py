"""export_hwpx: 파이프라인 S0~S6 (설계 3·4장). 무상태·무I/O(템플릿 로드 제외), 같은 입력 → 같은 바이트."""
from dataclasses import dataclass, field
from datetime import datetime

from .builders import (Equation, ParagraphSpec, Picture, TitlePart, blank_paragraph, build_problem_paragraphs,
                       clean_text, title_box_spec)
from .errors import EmptyExportError, MissingNumberError, UnconfirmedProblemError
from .header_patch import patch_header
from .layout import LayoutContext, plan_layout
from .package import build_zip, patch_hpf, strip_preview
from .preset import ExportPreset
from .registry import ParaKey, StyleRegistry
from .report import ExportReport
from .section import (FOOTER_INNER_LINE_PCT, FOOTER_NUM_LINE_PCT, FOOTER_OUTER_LINE_PCT, FOOTER_PT, FooterStyle,
                      HeaderMarkStyle, HEADER_MARK_LINE_PCT, HEADER_MARK_PT, render_section)
from .template import Template
from .validate import assert_valid


@dataclass
class ExportMeta:
    title: str = ""
    created: str | datetime = "2026-01-01T00:00:00Z"  # 입력으로 받아 결정적 출력을 보장
    subtitle: str = ""   # 첫 쪽 제목 상자의 부제(preset.title_box.enabled일 때만 쓴다)


@dataclass
class ExportRequest:
    problems: list
    preset: ExportPreset | dict | None = None
    meta: ExportMeta = field(default_factory=ExportMeta)
    images: object = None          # ImageProvider (M4)
    template_path: str | None = None


@dataclass
class ExportResult:
    hwpx_bytes: bytes
    report: ExportReport
    layout: dict


def _iso(v) -> str:
    return v.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(v, datetime) else str(v)


def _mm(hwp: int) -> str:
    """보고서 문장용 mm 표기(소수 한 자리, 끝의 .0은 뺀다)."""
    return f"{round(hwp * 25.4 / 7200, 1):g}mm"


def _preset(p) -> ExportPreset:
    if isinstance(p, ExportPreset):
        p.validate()
        return p
    preset = ExportPreset.from_dict(p)
    preset.validate()
    return preset


def _source_number(problem: dict) -> str:
    """원래 번호 문자열. 없으면 빈 문자열. XML에 넣을 수 없는 제어 문자는 뺀다."""
    return "".join(ch for ch in str(problem.get("source_number") or "") if ch.isprintable()).strip()


def _para_id(reg: StyleRegistry, layout: LayoutContext, s: ParagraphSpec) -> int:
    if s.role == "table":  # 표: 칸 안 문단은 가운데 정렬, 표를 담는 문단도 가운데 정렬
        b = s.parts[0]
        b.cell_pr = reg.para(ParaKey("CENTER", False, False))
        b.border_id = reg.table_border()
        return reg.para(ParaKey("CENTER", s.keep_with_next, s.keep_lines))
    if s.role == "title_box":  # 제목 표: 안쪽 글은 가운데 정렬, 표를 담는 문단은 왼쪽 정렬
        tp = s.parts[0]
        tp.para_pr = reg.para(ParaKey("CENTER", False, False))
        tp.border_id = reg.title_border()
        tp.title_char = reg.char(tp.title_size, tp.title_font or None)
        tp.sub_char = reg.char(tp.sub_size, tp.sub_font or None) if tp.sub_size else 0
        return reg.para(ParaKey("LEFT", False, False))
    if s.role == "box":  # 상자: 안쪽 본문은 왼쪽 정렬, <보기> 제목은 가운데 정렬(제목 없는 상자는 제목 문단 없음). 상자를 담는 문단은 왼쪽 정렬
        b = s.parts[0]
        b.body_pr = reg.para(ParaKey("LEFT", False, False))
        b.title_pr = reg.para(ParaKey("CENTER", False, False)) if b.title else 0
        return reg.para(ParaKey("LEFT", s.keep_with_next, s.keep_lines))
    if s.role == "choice":  # 선택지 행: 왼쪽 정렬 + 열 균등 탭 정지 [설계 7장]
        tab = reg.tab(layout.col_w, s.tab_cols) if s.tab_cols > 1 else 0
        return reg.para(ParaKey("LEFT", s.keep_with_next, s.keep_lines, tab))
    return reg.para(ParaKey(layout.align, s.keep_with_next, s.keep_lines))


def export_hwpx(req: ExportRequest) -> ExportResult:
    # S0
    preset = _preset(req.preset)
    layout: LayoutContext = plan_layout(preset)
    report = ExportReport(layout=layout.summary(), effective_preset=preset.to_dict())
    # 확정 여부
    chosen = []
    for p in req.problems:
        if p.get("status") != "confirmed":
            if preset.on_unconfirmed == "fail":
                raise UnconfirmedProblemError(f"확정되지 않은 문항: {p.get('id')}")
            report.add("NOT_CONFIRMED", "warn", "확정되지 않은 문항을 제외함", p.get("id"))
            continue
        chosen.append(p)
    if not chosen:
        raise EmptyExportError("내보낼 문항이 없음")
    # 원래 번호를 쓰는데 번호가 없는 문항이 있으면 번호를 지어내지 않고 멈춘다
    by_source = preset.numbering.mode == "source"
    if by_source:
        missing = sum(1 for p in chosen if not _source_number(p))
        if missing:
            raise MissingNumberError(f"원래 번호가 없는 문항: {missing}개")
    # S1
    tpl = Template.load(req.template_path)
    header = tpl.text("Contents/header.xml")
    # S2·S3 문항 → 문단 명세 (번호는 numbering.mode에 따라 내보낼 때 재부여하거나 원래 번호를 쓴다)
    specs: list = []
    n_text = 0
    emitted = 0  # 그림을 못 찾아 제외된 문항은 번호를 쓰지 않는다
    src_mode = preset.source.mode
    prev_exam = object()  # 시험지마다: 바로 앞 문항과 시험지가 달라지는 곳에 출처 줄을 둔다
    for prob in chosen:
        number = (_source_number(prob) if by_source
                  else preset.numbering.format.format(n=preset.numbering.start + emitted))
        ps = build_problem_paragraphs(prob, number, report, layout, preset.choices.safety_ratio,
                                      req.images, preset.figures.default_width_mm)
        if ps is None:
            continue
        emitted += 1
        label = (prob.get("source_label") or "").strip()
        if src_mode == "problem" and label:   # 번호 문단 끝에 붙인다
            ps[0].parts.append(f"  [{label}]")
        if src_mode == "exam":
            if prob.get("exam_id") != prev_exam and label:   # 출처 줄은 뒤따르는 문항과 같은 쪽에 둔다
                specs.append(ParagraphSpec([f"[{label}]"], True, True, role="source"))
            prev_exam = prob.get("exam_id")
        specs.extend(ps)
        specs.extend(blank_paragraph() for _ in range(preset.spacing.blank_lines))
    if not specs:
        raise EmptyExportError("내보낼 문항이 없음(모든 문항이 제외됨)")
    title_on = False
    title_fonts: list = []   # 제목 표에 실제로 쓰인 글꼴(안내용)
    if preset.title_box.enabled:   # 첫 쪽 맨 위: 본문 폭 전체의 제목 표(1단 구역). 이어서 단 설정을 나눈다
        tb = title_box_spec(req.meta.title, req.meta.subtitle, layout, preset.title_box.big_font, preset.title_box.small_font)
        if tb is None:
            report.add("TITLE_BOX_NO_TITLE", "warn", "제목이 비어 있어 제목 상자를 넣지 않음")
        else:
            specs.insert(0, tb)
            title_on = True
            title_fonts = [f for f in (tb.parts[0].title_font, tb.parts[0].sub_font) if f]
            report.add("TITLE_BOX_HEIGHT_ESTIMATED", "info", "제목 상자 높이는 줄 수로 추정한 값 [제안: 한글 확인 필요]")
    mark_text = clean_text(preset.header_mark.text).strip()   # 머리 표식: 글자가 있을 때만 둘째 쪽부터(제목 상자가 없으면 첫 쪽부터)
    # 여백을 올린 안전장치(plan_layout)를 알린다. 이 두 문장은 웹에도 그대로 나간다(messages.REPORT_PASSTHROUGH)
    if layout.header_raised_from is not None:
        report.add("HEADER_MARK_TALL", "warn",
                   f"머리 표식이 머리말 여백보다 높아 그대로면 본문과 겹칠 수 있어서, 머리말 여백을 "
                   f"{_mm(layout.header_raised_from)}에서 {_mm(layout.header)}로 올렸어요.")
    if layout.footer_raised_from is not None:
        report.add("FOOTER_TALL", "warn",
                   f"쪽 번호가 꼬리말 여백보다 높아 그대로면 본문과 겹칠 수 있어서, 꼬리말 여백을 "
                   f"{_mm(layout.footer_raised_from)}에서 {_mm(layout.footer)}로 올렸어요.")
    pics = [p for s in specs for p in s.parts if isinstance(p, Picture)]
    for k, p in enumerate(pics, start=1):  # 문서 순서대로 image1, image2 …
        p.bin_id = k
    n_text = sum(1 for s in specs if s.role == "body")
    n_eq = sum(1 for s in specs for p in s.parts if isinstance(p, Equation))
    n_wrapped = sum(1 for s in specs for p in s.parts if isinstance(p, Equation) and p.wrapped)
    if preset.equation.size_mode != "auto":
        report.add("NOT_IMPLEMENTED", "warn",
                   f"equation.size_mode='{preset.equation.size_mode}'는 아직 지원하지 않아 'auto'로 처리함(설계 10장 확장점)")
    # 스타일 ID 할당(첫 사용 순서)
    reg = StyleRegistry(header, layout.line_spacing_pct)
    paragraphs = [(_para_id(reg, layout, s), s.parts) for s in specs]
    footer = None   # "- 1 -"은 쪽 번호 ctrl로, "1 / 5"·상자는 꼬리말로 넣는다
    if layout.page_number and layout.page_number_style == "box":   # 샘플 꼬리말: 줄간격은 본문 설정과 무관한 고정값
        fp = lambda align, pct: reg.para(ParaKey(align, False, False, line_spacing=pct))
        footer = FooterStyle(reg.para(ParaKey("CENTER", False, False)), reg.slash_border(), reg.plain_border(),
                             fp("CENTER", FOOTER_OUTER_LINE_PCT), fp("CENTER", FOOTER_INNER_LINE_PCT),
                             fp("LEFT", FOOTER_NUM_LINE_PCT), fp("RIGHT", FOOTER_NUM_LINE_PCT), reg.char(FOOTER_PT))
    elif layout.page_number and layout.page_number_style != "dash":
        footer = FooterStyle(reg.para(ParaKey("CENTER", False, False)))
    mark = None
    if mark_text:
        hp = lambda align: reg.para(ParaKey(align, False, False, line_spacing=HEADER_MARK_LINE_PCT))   # 본문 줄간격과 무관(샘플 160%)
        mark = HeaderMarkStyle(mark_text, hp("LEFT"), hp("RIGHT"), hp("CENTER"), reg.title_border(), reg.char(HEADER_MARK_PT))
        report.add("HEADER_MARK_ESTIMATED", "info", "머리 표식 크기·위치는 샘플을 따른 값 [제안: 한글 확인 필요]")
    # S4
    new_header = patch_header(header, layout, preset.typography.font_name, reg)
    section = render_section(tpl.text("Contents/section0.xml"), layout, paragraphs, footer, title_on, mark)
    # S5
    parts = strip_preview(tpl.copy_parts())
    parts["Contents/header.xml"] = new_header.encode("utf-8")
    parts["Contents/section0.xml"] = section.encode("utf-8")
    parts["Contents/content.hpf"] = patch_hpf(tpl.text("Contents/content.hpf"), req.meta.title,
                                              _iso(req.meta.created), len(pics)).encode("utf-8")
    for p in pics:
        parts[f"BinData/image{p.bin_id}.png"] = p.png
    data = build_zip(parts)
    # S6
    assert_valid(data)
    fonts = [preset.typography.font_name] + title_fonts
    names = ", ".join(f"'{f}'" for f in dict.fromkeys(fonts))   # 겹치는 이름은 한 번만
    report.add("FONT_NOT_VERIFIED", "info", f"글꼴 {names}이(가) 사용자 PC에 있는지 알 수 없음")
    report.stats.update({"problems": emitted, "figures": len(pics), "paragraphs": len(specs), "text_paragraphs": n_text,
                         "new_para_pr": len(reg.new_para_xml),
                         "equations": n_eq, "equations_wrapped": n_wrapped,
                         "boxes": sum(1 for s in specs if s.role == "box"),
                         "tables": sum(1 for s in specs if s.role == "table"),
                         "choice_rows": sum(1 for s in specs if s.role == "choice"), "new_tab_pr": len(reg.new_tab_xml)})
    return ExportResult(data, report, layout.summary())
