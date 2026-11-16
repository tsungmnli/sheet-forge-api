"""B5-3b-1: 읽기 결과(read_crop의 정규화 결과) -> REST content 계약 (설계 6.3). 순수 함수, LLM 호출 없음.
- stem 문단에 type="paragraph"를 붙이고, 조각의 null 필드를 지운다(text는 t·v만, math는 t·latex만).
- choices는 문단 배열 -> {"items": [조각 배열, ...], "layout": "auto"}. 선택지가 없으면 None.
- figures는 여기서 다루지 않는다. 크롭 좌표를 보정본 좌표로 바꾸고 그림 항목을 만드는 일은 이후 단계이며, 지금은 빈 목록이다.
- 입력은 바꾸지 않는다."""


def _inline(i: dict) -> dict:
    if i["t"] == "math":
        return {"t": "math", "latex": i["latex"]}
    return {"t": "text", "v": i["v"]}


def _inlines(p: dict) -> list:
    return [_inline(i) for i in p["inlines"]]


def to_content(obj: dict) -> dict:
    stem = [{"type": "paragraph", "inlines": _inlines(p)} for p in obj["stem"]]
    ch = obj.get("choices")
    choices = {"items": [_inlines(p) for p in ch], "layout": "auto"} if ch else None
    return {"stem": stem, "choices": choices, "figures": []}
