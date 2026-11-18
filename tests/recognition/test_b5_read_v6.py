"""B5-5c: read_v6 프롬프트와 읽기 스키마의 box·table 블록 (LLM 호출 없음)."""
from app.recognition.llm.read import PROMPT_PATH, PROMPT_VERSION, load_prompt
from app.recognition.llm.schemas import READ_SCHEMA


def test_prompt_version_and_placeholder():
    assert PROMPT_VERSION == "read_v6"
    assert PROMPT_PATH.name == "read_v6.md"
    assert PROMPT_PATH.read_text(encoding="utf-8").count("{{VOCAB}}") == 1
    text = load_prompt()
    assert "{{VOCAB}}" not in text and "\r" not in text


def test_prompt_describes_box_and_table_blocks():
    text = load_prompt()
    for key in ("type=box", "type=table", "rows", "title", "unsupported_block"):
        assert key in text
    assert "(6번 규칙)" in text and "<보기> 상자의 줄마다다" not in text


def test_schema_stem_blocks():
    blocks = {b["properties"]["type"]["enum"][0]: b for b in READ_SCHEMA["properties"]["stem"]["items"]["anyOf"]}
    assert list(blocks) == ["paragraph", "box", "table"]
    assert blocks["paragraph"]["required"] == ["type", "inlines"]
    assert blocks["box"]["required"] == ["type", "title", "paragraphs"]   # title만 있는 box는 스키마에서 막는다
    assert blocks["box"]["properties"]["title"]["nullable"] is True
    assert blocks["box"]["properties"]["paragraphs"]["items"]["required"] == ["inlines"]
    assert blocks["table"]["required"] == ["type", "rows"]
    assert blocks["table"]["properties"]["rows"]["items"]["items"]["items"]["required"] == ["t", "v", "latex"]   # 행 -> 칸 -> 조각
