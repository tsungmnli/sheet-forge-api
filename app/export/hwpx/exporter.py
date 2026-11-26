"""export_hwpx: 파이프라인 S0~S6 (설계 3·4장). 무상태·무I/O(템플릿 로드 제외), 같은 입력 → 같은 바이트."""
from dataclasses import dataclass, field
from datetime import datetime

from .builders import Equation, ParagraphSpec, Picture, blank_paragraph, build_problem_paragraphs
from .errors import EmptyExportError, MissingNumberError, UnconfirmedProblemError
from .header_patch import patch_header
from .layout import LayoutContext, plan_layout
from .package import build_zip, patch_hpf, strip_preview
from .preset import ExportPreset
from .registry import ParaKey, StyleRegistry
from .report import ExportReport
from .section import render_section
from .template import Template
from .validate import assert_valid


@dataclass
class ExportMeta:
    title: str = ""
    created: str | datetime = "2026-01-01T00:00:00Z"  # 입력으로 받아 결정적 출력을 보장


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
    for prob in chosen:
        number = (_source_number(prob) if by_source
                  else preset.numbering.format.format(n=preset.numbering.start + emitted))
        ps = build_problem_paragraphs(prob, number, report, layout, preset.choices.safety_ratio,
                                      req.images, preset.figures.default_width_mm)
        if ps is None:
            continue
        emitted += 1
        specs.extend(ps)
        specs.extend(blank_paragraph() for _ in range(preset.spacing.blank_lines))
    if not specs:
        raise EmptyExportError("내보낼 문항이 없음(모든 문항이 제외됨)")
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
    # S4
    new_header = patch_header(header, layout, preset.typography.font_name, reg)
    section = render_section(tpl.text("Contents/section0.xml"), layout, paragraphs)
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
    report.add("FONT_NOT_VERIFIED", "info", f"글꼴 '{preset.typography.font_name}'이 사용자 PC에 있는지 알 수 없음")
    report.stats.update({"problems": emitted, "figures": len(pics), "paragraphs": len(specs), "text_paragraphs": n_text,
                         "new_para_pr": len(reg.new_para_xml),
                         "equations": n_eq, "equations_wrapped": n_wrapped,
                         "boxes": sum(1 for s in specs if s.role == "box"),
                         "tables": sum(1 for s in specs if s.role == "table"),
                         "choice_rows": sum(1 for s in specs if s.role == "choice"), "new_tab_pr": len(reg.new_tab_xml)})
    return ExportResult(data, report, layout.summary())
