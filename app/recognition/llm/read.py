"""B5-3a-2: 읽기 호출 (문제 크롭 -> 축소 JPEG -> LLM 1회 -> 파싱·검증 -> 정규화). 설계 6.1~6.4의 0번.
공급자는 모르고 LlmClient 포트만 쓴다. 호출 실패(LlmError)와 출력 형태 이상(ReadParseError)은 그대로 올라온다.
스키마 검증 실패 시 같은 모델로 1회 다시 부르는 일, 수식 변환기 점검과 수리 호출은 B5-3b에서 한다.
content 계약(문단 type, 선택지 items, 그림 좌표 변환)으로 맞추는 어댑터도 B5-3b다."""
import json
import logging
import math
import re
from pathlib import Path

from ...export.math import vocab as V
from ..ports import LlmLimits
from .repair import normalize_read
from .schemas import READ_SCHEMA
from .segment import shrink_for_segment

log = logging.getLogger("sheet_forge.recognition")

PROMPT_VERSION = "read_v5"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / (PROMPT_VERSION + ".md")
READ_LONG_SIDE = 1000       # 설계 6.1: 크롭을 긴 변 약 1,000px로(작으면 확대하지 않는다)
DEFAULT_MAX_OUTPUT = 4096   # 설계는 약 2,000. 추론 설정(B5-3b)이 정해지기 전이라 넉넉히 둔다

# 파서(app/export/math/parser.py)가 다루는 구조 명령. 기호·함수는 vocab.py에서 뽑는다.
STRUCT = r"\frac{분자}{분모}, \sqrt{}, 위 첨자 ^, 아래 첨자 _, \overline{}, \dot{}(글자 위 점), \left … \right, \begin{cases} … \end{cases}, \text{}, \mathrm{}"


class ReadParseError(ValueError):
    """kind: not_json | bad_shape. 메시지에는 종류만 담는다(응답 내용 없음)."""


def vocab_text() -> str:
    """허용 어휘 한 줄. 변환기가 기본으로 막는 documented 어휘는 뺀다(검증된 것만)."""
    sym = " ".join("\\" + k for k, (_, st) in V.SYMBOLS.items() if st == V.VERIFIED)
    fn = " ".join("\\" + k for k, st in V.FUNCS.items() if st == V.VERIFIED)
    return f"구조 {STRUCT} / 기호 {sym} / 함수 {fn} (이 밖의 명령은 쓰지 않는다)"


def load_prompt() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    return text.replace("{{VOCAB}}", vocab_text())


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)
# 짝을 이룬 역슬래시 쌍은 두고, 유효한 JSON 이스케이프가 아닌 단독 역슬래시(\le, \left 등)만 두 번으로 바꾼다
_BAD_ESC = re.compile(r'(\\\\)|\\(?!["/bfnrt]|u[0-9a-fA-F]{4})')


def _loads(text):
    s = (text or "").strip()
    m = _FENCE.match(s)
    if m:
        s = m.group(1)
    for cand in (s, _BAD_ESC.sub(lambda m: m.group(1) or "\\\\", s)):   # 두 번째는 첫 시도가 실패했을 때만 쓴다
        try:
            return json.loads(cand)
        except ValueError:
            continue
    raise ReadParseError("not_json")


def _inlines(v):
    if not isinstance(v, list):
        raise ReadParseError("bad_shape")
    out = []
    for it in v:
        if not isinstance(it, dict) or it.get("t") not in ("text", "math"):
            raise ReadParseError("bad_shape")
        if it["t"] == "text":
            val = "" if it.get("v") is None else it["v"]
            if not isinstance(val, str):
                raise ReadParseError("bad_shape")
            out.append({"t": "text", "v": val, "latex": None})
        else:
            if not isinstance(it.get("latex"), str):
                raise ReadParseError("bad_shape")
            out.append({"t": "math", "v": None, "latex": it["latex"]})
    return out


def _paragraphs(v):
    if not isinstance(v, list):
        raise ReadParseError("bad_shape")
    out = []
    for p in v:
        if not isinstance(p, dict):
            raise ReadParseError("bad_shape")
        out.append({"inlines": _inlines(p.get("inlines"))})
    return out


def _block(b):
    """stem 블록 하나. type이 없거나 paragraph이면 {"inlines"} 그대로(기존 모양), box·table은 type을 단 채로 돌려준다.
    내용이 없는 상자·표는 None(버린다). 모르는 type은 bad_shape."""
    if not isinstance(b, dict):
        raise ReadParseError("bad_shape")
    t = b.get("type")
    if t is None or t == "paragraph":
        return {"inlines": _inlines(b.get("inlines"))}
    if t == "box":
        title = b.get("title")
        if title is not None and not isinstance(title, str):
            raise ReadParseError("bad_shape")
        paras = _paragraphs(b.get("paragraphs"))
        return {"type": "box", "title": title, "paragraphs": paras} if paras else None
    if t == "table":
        rows = b.get("rows")
        if not isinstance(rows, list) or not all(isinstance(r, list) for r in rows):
            raise ReadParseError("bad_shape")
        rows = [[_inlines(c) for c in r] for r in rows]
        return {"type": "table", "rows": rows} if any(rows) else None
    raise ReadParseError("bad_shape")


def _blocks(v):
    if not isinstance(v, list):
        raise ReadParseError("bad_shape")
    return [x for x in (_block(b) for b in v) if x is not None]


def _figure(f):
    box = f.get("box_2d") if isinstance(f, dict) else None
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        nums = [float(x) for x in box]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) for x in nums):
        return None
    pl = f.get("placement")
    return {"box_2d": nums, "placement": pl if pl in ("after_stem", "after_choices") else "after_stem"}


def _points(v):
    """배점은 0 이상 1000 이하의 유한한 숫자만 받는다(PUT content의 points 검증과 같은 범위). 그 밖은 None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1000:
        return None
    return float(v)


def parse_read_json(text: str) -> dict:
    """LLM 출력(JSON 문자열) -> {"stem","choices","figures","uncertain","unsupported_block","points"}.
    stem은 문단({"inlines"}, 기존 모양 그대로)과 type이 box·table인 블록의 목록이다. 내용 없는 상자·표는 버린다.
    stem·choices의 형태가 틀리면 ReadParseError. 빠진 선택 필드는 기본값으로 채우고, 좌표가 틀린 그림 항목은 버린다."""
    data = _loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("stem"), list):
        raise ReadParseError("bad_shape")
    choices = data.get("choices")
    figures = data.get("figures")
    uncertain = data.get("uncertain")
    block = data.get("unsupported_block")
    out = {
        "stem": _blocks(data["stem"]),
        "choices": None if choices is None else _paragraphs(choices),
        "figures": [f for f in (_figure(x) for x in figures) if f] if isinstance(figures, list) else [],
        "uncertain": [{"where": str(u.get("where", "")), "reason": str(u.get("reason", ""))}
                      for u in uncertain if isinstance(u, dict)] if isinstance(uncertain, list) else [],
        "unsupported_block": block if isinstance(block, str) else None,
        "points": _points(data.get("points")),
    }
    # 진단용: 문제 내용은 남기지 않고 개수만 남긴다. figures는 (쓸 수 있는 것/모델이 준 것)이다.
    log.info("읽기 결과 stem=%d choices=%s figures=%d/%d uncertain=%d points=%s block=%s",
             len(out["stem"]), "없음" if out["choices"] is None else len(out["choices"]),
             len(out["figures"]), len(figures) if isinstance(figures, list) else 0, len(out["uncertain"]),
             "있음" if out["points"] is not None else "없음", "있음" if out["unsupported_block"] else "없음")
    return out


def read_crop(client, model: str, crop: bytes, *, long_side: int = READ_LONG_SIDE, limits: LlmLimits | None = None):
    """(정규화한 읽기 결과 dict, LlmResult, 고친 조각 수)를 돌려준다. LlmResult는 usage_events 기록용(B5-3c)."""
    limits = limits or LlmLimits(max_output_tokens=DEFAULT_MAX_OUTPUT)
    result = client.generate(model, shrink_for_segment(crop, long_side), load_prompt(), READ_SCHEMA, limits)
    try:
        obj = parse_read_json(result.text)
    except ReadParseError as e:
        # 응답 내용은 남기지 않고, 어떻게 깨졌는지만 알린다(진단용)
        raise ReadParseError(f"{e} finish={result.finish_reason} out={result.output_tokens} think={result.thinking_tokens} chars={len(result.text)}") from None
    return obj, result, normalize_read(obj)
