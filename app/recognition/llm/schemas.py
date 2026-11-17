"""B5-2b-2·B5-3a-2: LLM 구조 출력 스키마. 공급자 SDK와 무관한 JSON Schema 조각(어댑터가 responseSchema로 보낸다).
분할 좌표는 이미지 전체를 0~1000으로 정규화한 [ymin, xmin, ymax, xmax]."""
_BOX = {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}
_BOX_OR_NULL = dict(_BOX, nullable=True)

SEGMENT_SCHEMA = {
    "type": "object",
    "properties": {"problems": {"type": "array", "items": {
        "type": "object",
        "properties": {"number": {"type": "string", "nullable": True}, "box_2d": _BOX,
                       "choices_box_2d": _BOX_OR_NULL, "figure_box_2d": _BOX_OR_NULL},
        "required": ["number", "box_2d", "choices_box_2d", "figure_box_2d"]}}},
    "required": ["problems"],
}

# 읽기 출력(설계 6.3). 조각의 text는 v만, math는 latex만 채우고 나머지는 null.
_INLINE = {"type": "object",
           "properties": {"t": {"type": "string", "enum": ["text", "math"]},
                          "v": {"type": "string", "nullable": True},
                          "latex": {"type": "string", "nullable": True}},
           "required": ["t", "v", "latex"]}
_PARAGRAPHS = {"type": "array", "items": {"type": "object",
                                          "properties": {"inlines": {"type": "array", "items": _INLINE}},
                                          "required": ["inlines"]}}

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "stem": _PARAGRAPHS,
        "choices": dict(_PARAGRAPHS, nullable=True),
        "figures": {"type": "array", "items": {
            "type": "object",
            "properties": {"box_2d": _BOX, "placement": {"type": "string", "enum": ["after_stem", "after_choices"]}},
            "required": ["box_2d", "placement"]}},
        "uncertain": {"type": "array", "items": {
            "type": "object",
            "properties": {"where": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["where", "reason"]}},
        "unsupported_block": {"type": "string", "nullable": True},
        "points": {"type": "number", "nullable": True},   # 인쇄된 배점 숫자("[4점]" -> 4). 없으면 null
    },
    "required": ["stem", "choices", "figures", "uncertain", "unsupported_block", "points"],
}
