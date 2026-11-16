"""B5-3b-3: 수식 수리 호출(설계 6.4의 2). 변환 불가 수식만 담아 텍스트 전용으로 LLM을 1회 부르고,
다시 변환기를 통과한 것만 교체한다. 수리는 최선 노력이다: 호출·파싱이 실패해도 예외를 올리지 않고
error_kind에 종류만 담아 돌려주며, 이때 읽기 결과는 그대로이고 failures는 모두 남는다(끝내 남은 것은 math_warning 힌트).
입력 obj는 바꾸지 않는다. 로그에는 개수·종류만 남기고 latex는 남기지 않는다."""
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from ...export.math.convert import convert
from ..ports import LlmError, LlmLimits
from .read import ReadParseError, _loads, vocab_text
from .repair import _CTRL, _CTRL_RE

PROMPT_VERSION = "repair_v1"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / (PROMPT_VERSION + ".md")
MAX_OUTPUT = 2000

REPAIR_SCHEMA = {
    "type": "object",
    "properties": {"fixes": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "latex": {"type": "string"}},
        "required": ["id", "latex"]}}},
    "required": ["fixes"],
}


@dataclass
class RepairOutcome:
    obj: dict                                   # 고친 읽기 결과(고친 것이 없으면 입력 그대로)
    usage: object = None                        # LlmResult. 호출하지 않았거나 호출이 실패하면 None (usage_events는 B5-3c)
    fixed: int = 0
    remaining: list = field(default_factory=list)   # 끝내 변환 불가인 failures 항목(check_math 형식)
    error_kind: str | None = None               # LlmError.kind 또는 not_json | bad_shape. 정상이면 None


def load_repair_prompt(items: list) -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    return text.replace("{{VOCAB}}", vocab_text()).replace("{{ITEMS}}", json.dumps(items, ensure_ascii=False))


def repair_math(client, model: str, obj: dict, failures: list, *, limits: LlmLimits | None = None,
                convert_fn=convert) -> RepairOutcome:
    if not failures:
        return RepairOutcome(obj)
    limits = limits or LlmLimits(max_output_tokens=MAX_OUTPUT)
    items = [{"id": i, "latex": f["latex"], "error": f["error"], "error_pos": f["error_pos"]}
             for i, f in enumerate(failures)]
    try:
        result = client.generate(model, None, load_repair_prompt(items), REPAIR_SCHEMA, limits)
    except LlmError as e:
        return RepairOutcome(obj, None, 0, list(failures), e.kind)
    try:
        data = _loads(result.text)
        fixes = data.get("fixes") if isinstance(data, dict) else None
        if not isinstance(fixes, list):
            raise ReadParseError("bad_shape")
    except ReadParseError as e:
        return RepairOutcome(obj, result, 0, list(failures), str(e))
    new, done = copy.deepcopy(obj), set()
    for fx in fixes:
        if not isinstance(fx, dict):
            continue
        i, latex = fx.get("id"), fx.get("latex")
        if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(failures) or i in done:
            continue
        if not isinstance(latex, str):
            continue
        latex = _CTRL_RE.sub(lambda m: _CTRL[m.group()], latex)   # 읽기와 같은 이스케이프 복구(\\f 등이 제어문자로 풀린 경우)
        if latex == failures[i]["latex"]:
            continue
        try:
            ok = convert_fn(latex).ok
        except Exception:  # noqa: BLE001 — 변환기 오류는 고쳐지지 않은 것으로 본다
            ok = False
        if not ok:
            continue
        f = failures[i]
        new[f["area"]][f["para"]]["inlines"][f["inline"]]["latex"] = latex
        done.add(i)
    remaining = [f for i, f in enumerate(failures) if i not in done]
    return RepairOutcome(new, result, len(done), remaining, None)
