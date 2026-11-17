"""문제 내용 처리(DB 없음): 검증, 쉬운 요약, 점검(hints·blockers), 검색용 평문, 그림 병합 (웹 REST API 설계 5.5).

content 구조는 README 6.3 그대로(stem / choices / figures). 선택지 기호와 문항 번호는 저장하지 않는다.
"""
import re

from ..export.math.convert import convert
from .errors import ApiError
from .schemas import ContentIn

INLINE_TYPES = ("text", "math", "image")
PLACEMENTS = ("after_stem", "after_choices")
LOW_CONF = 0.7                 # 이보다 낮은 인식 신뢰도는 "여기부터 보세요"로 알린다
MAX_STEM_BLOCKS = 50
MAX_CHOICES = 10
MAX_INLINES = 300
MAX_TEXT = 5000
MAX_LATEX = 2000
MAX_FIGURES = 20
MSG_UNSUPPORTED = "이 수식은 아직 한글 수식으로 바꿀 수 없어요."
MSG_EMPTY_MATH = "수식이 비어 있어요."
MSG_MATH_NOTE = "이 수식은 한글에서 한 번 확인해 보면 좋아요."


def empty_content() -> dict:
    return {"stem": [], "choices": {"items": [], "layout": "auto"}, "figures": []}


def iter_inlines(content: dict):
    """(경로, inline) 목록. 경로는 stem/0/inlines/3, choices/items/2/0 형식(웹이 그 자리로 이동하는 데 쓴다)."""
    for bi, block in enumerate(content.get("stem") or []):
        for ii, inl in enumerate(block.get("inlines") or []):
            yield f"stem/{bi}/inlines/{ii}", inl
    for ci, item in enumerate((content.get("choices") or {}).get("items") or []):
        for ii, inl in enumerate(item or []):
            yield f"choices/items/{ci}/{ii}", inl


def _bad(message: str) -> ApiError:
    return ApiError(422, "REQUEST_INVALID", message)


def normalize_content(content_in: ContentIn, stored_figures: list | None = None) -> dict:
    """요청의 content를 검증하고 기본값을 채운다. 그림은 서버가 관리하므로 stored_figures와 병합한다."""
    c = content_in.model_dump(exclude_none=True)
    c.setdefault("stem", [])
    c.setdefault("figures", [])
    c.setdefault("choices", {"items": [], "layout": "auto"})
    c["choices"].setdefault("items", [])
    c["choices"].setdefault("layout", "auto")
    if len(c["stem"]) > MAX_STEM_BLOCKS or len(c["choices"]["items"]) > MAX_CHOICES:
        raise _bad("문단이나 선택지가 너무 많아요.")
    valid_refs = set()
    for f in stored_figures or []:
        valid_refs.update(v for v in (f.get("id"), f.get("raw_ref"), f.get("clean_ref")) if v)
    n = 0
    for _, inl in iter_inlines(c):
        n += 1
        t = inl.get("t")
        if t not in INLINE_TYPES:
            raise _bad("알 수 없는 내용 조각이 있어요.")
        if t == "text":
            v = inl.setdefault("v", "")
            if not isinstance(v, str) or len(v) > MAX_TEXT:
                raise _bad("글이 너무 길어요.")
        elif t == "math":
            latex = inl.setdefault("latex", "")
            if not isinstance(latex, str) or len(latex) > MAX_LATEX:
                raise _bad("수식이 너무 길어요.")
        elif inl.get("ref") is not None and inl["ref"] not in valid_refs:
            raise ApiError(422, "FIGURE_REF_INVALID")
    if n > MAX_INLINES:
        raise _bad("한 문제에 넣을 수 있는 조각 수를 넘었어요.")
    c["figures"] = merge_figures(c["figures"], stored_figures or [])
    return c


def merge_figures(submitted: list, stored: list) -> list:
    """그림은 서버가 만든 것만 있다. 요청에서는 use·placement·width_mm만 바꿀 수 있고, 모르는 그림이나 다른 ref는 거절한다.

    요청에서 빠진 그림은 지우지 않는다(지우기는 DELETE …/figures/{fid}).
    """
    by_id = {f["id"]: f for f in stored}
    edits = {}
    for f in submitted:
        cur = by_id.get(f.get("id"))
        if cur is None:
            raise ApiError(422, "FIGURE_REF_INVALID")
        for k in ("raw_ref", "clean_ref"):
            if k in f and f[k] != cur.get(k):
                raise ApiError(422, "FIGURE_REF_INVALID")
        edits[cur["id"]] = f
    out = []
    for cur in stored:
        new = dict(cur)
        f = edits.get(cur["id"])
        if f is not None:
            if "use" in f:
                if f["use"] not in ("raw", "clean"):
                    raise _bad("그림 사용 값이 올바르지 않아요.")
                new["use"] = f["use"]
            if "placement" in f:
                if f["placement"] not in PLACEMENTS:
                    raise _bad("그림 위치 값이 올바르지 않아요.")
                new["placement"] = f["placement"]
            if "width_mm" in f:
                w = f["width_mm"]
                if isinstance(w, bool) or not isinstance(w, (int, float)) or not 5 <= w <= 400:
                    raise _bad("그림 너비 값이 올바르지 않아요.")
                new["width_mm"] = w
        out.append(new)
    return out


def preview(content: dict, limit: int = 100) -> str:
    """목록에 보여 줄 쉬운 평문 요약. 수식은 LaTeX 원문 그대로."""
    parts = []
    for block in content.get("stem") or []:
        for inl in block.get("inlines") or []:
            t = inl.get("t")
            if t == "text":
                parts.append(inl.get("v") or "")
            elif t == "math":
                parts.append(inl.get("latex") or "")
    s = " ".join("".join(parts).split())
    return s if len(s) <= limit else s[:limit].rstrip() + "…"


def preview_tex(content: dict, limit: int = 100) -> str:
    """목록 렌더링용 요약. preview와 같지만 수식을 $…$로 감싼다. 수식은 중간에서 자르지 않는다."""
    out, n, cut = [], 0, False
    for block in content.get("stem") or []:
        for inl in block.get("inlines") or []:
            t = inl.get("t")
            if t == "text":
                s = re.sub(r"\s+", " ", inl.get("v") or "")
                if n + len(s) > limit:
                    out.append(s[: limit - n].rstrip())
                    cut = True
                    break
                out.append(s)
                n += len(s)
            elif t == "math":
                latex = (inl.get("latex") or "").strip()
                if not latex:
                    continue
                if n + len(latex) > limit:
                    cut = True
                    break
                out.append("$" + latex + "$")
                n += len(latex)
        if cut:
            break
        out.append(" ")
    s = "".join(out).strip()
    return s + "…" if cut else s


def search_text(content: dict, limit: int = 20000) -> str:
    parts = []
    for _, inl in iter_inlines(content):
        if inl.get("t") == "text":
            parts.append(inl.get("v") or "")
        elif inl.get("t") == "math":
            parts.append(inl.get("latex") or "")
    return " ".join(" ".join(parts).split())[:limit]


def analyze(content: dict):
    """(hints, blockers, has_content). hints는 저장하지 않고 읽을 때마다 계산한다."""
    hints, blockers, has = [], [], False
    for path, inl in iter_inlines(content):
        t = inl.get("t")
        if t == "text":
            has = has or bool((inl.get("v") or "").strip())
        elif t == "image":
            has = True
        elif t == "math":
            latex = inl.get("latex") or ""
            has = has or bool(latex.strip())
            if not latex.strip():
                blockers.append({"path": path, "code": "MATH_UNSUPPORTED", "message": MSG_EMPTY_MATH})
            else:
                r = convert(latex)
                if not r.ok:
                    blockers.append({"path": path, "code": "MATH_UNSUPPORTED", "message": MSG_UNSUPPORTED})
                elif r.warnings:
                    hints.append({"path": path, "kind": "math_warning", "message": MSG_MATH_NOTE})
        conf = inl.get("conf")
        if isinstance(conf, (int, float)) and not isinstance(conf, bool) and conf < LOW_CONF:
            hints.append({"path": path, "kind": "low_confidence"})
    if content.get("figures"):
        has = True
    return hints, blockers, has


def check_math(latex: str) -> dict:
    """수식 입력기용 상태 확인(스크립트는 돌려주지 않는다)."""
    if not (latex or "").strip():
        return {"status": "unsupported", "message": MSG_EMPTY_MATH, "est_width": None}
    r = convert(latex)
    if not r.ok:
        return {"status": "unsupported", "message": MSG_UNSUPPORTED, "est_width": None}
    width = round(float(r.est_width_em), 2)
    if r.warnings:
        return {"status": "warn", "message": MSG_MATH_NOTE, "est_width": width}
    return {"status": "ok", "message": None, "est_width": width}


def normalize_read_content(raw: dict) -> dict:
    """인식기 결과를 저장 모양으로 맞춘다. 인식된 그림은 B5에서 그림 항목과 정리 작업으로 바뀐다(지금은 비움)."""
    choices = dict(raw.get("choices") or {})
    choices.setdefault("items", [])
    choices.setdefault("layout", "auto")
    return {"stem": list(raw.get("stem") or []), "choices": choices, "figures": []}
