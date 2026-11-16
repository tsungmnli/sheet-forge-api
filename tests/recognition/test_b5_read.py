"""B5-3a-2: 읽기 호출(어휘 채우기, 파싱·검증, 역슬래시 복구, 정규화, 오류 전파). 가짜 LlmClient를 쓴다."""
import io
import json
import unittest

from PIL import Image

from app.recognition.llm.read import (PROMPT_PATH, ReadParseError, load_prompt, parse_read_json, read_crop,
                                       vocab_text)
from app.recognition.llm.schemas import READ_SCHEMA
from app.recognition.ports import LlmError, LlmResult


def png(w, h):
    out = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(out, "PNG")
    return out.getvalue()


class FakeClient:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def generate(self, model, image, prompt, schema, limits):
        self.calls.append((model, image, prompt, schema, limits))
        if self.error:
            raise self.error
        return LlmResult(text=self.text, model=model, input_tokens=900, output_tokens=200)


def doc(stem, choices=None, **extra):
    d = {"stem": stem, "choices": choices, "figures": [], "uncertain": [], "unsupported_block": None}
    d.update(extra)
    return d


def para(*inl):
    return {"inlines": list(inl)}


def T(v):
    return {"t": "text", "v": v, "latex": None}


def M(s):
    return {"t": "math", "v": None, "latex": s}


class PromptTest(unittest.TestCase):
    def test_file_has_placeholder_and_loaded_prompt_is_filled(self):
        raw = PROMPT_PATH.read_text(encoding="utf-8")
        self.assertEqual(raw.count("{{VOCAB}}"), 1)
        text = load_prompt()
        self.assertNotIn("{{VOCAB}}", text)
        self.assertNotIn("\r", text)
        self.assertIn(vocab_text(), text)

    def test_vocab_has_verified_only(self):
        v = vocab_text()
        for ok in ("\\frac", "\\sqrt", "\\le ", "\\ge ", "\\times", "\\triangle", "\\sin", "\\lim", "\\theta"):
            self.assertIn(ok, v)
        for blocked in ("\\exists", "\\supset", "\\gamma", "\\max", "\\arcsin"):   # documented: 변환기가 기본으로 막는다
            self.assertNotIn(blocked, v)


class ParseTest(unittest.TestCase):
    def test_parses_and_fills_defaults(self):
        r = parse_read_json(json.dumps({"stem": [para(T("값은 "), M("x"), {"t": "text", "v": None, "latex": None})]}))
        self.assertEqual(r["choices"], None)
        self.assertEqual((r["figures"], r["uncertain"], r["unsupported_block"]), ([], [], None))
        self.assertEqual(r["stem"][0]["inlines"][2], {"t": "text", "v": "", "latex": None})

    def test_code_fence_and_figures_uncertain(self):
        text = "```json\n" + json.dumps(doc([para(T("가"))], figures=[
            {"box_2d": [100, 200, 500, 800], "placement": "after_choices"}, {"box_2d": [1, 2, 3]}, "x",
            {"box_2d": [0, 0, 10, 10], "placement": "weird"}],
            uncertain=[{"where": "stem 첫 문단", "reason": "smudged"}, 5], unsupported_block="box")) + "\n```"
        r = parse_read_json(text)
        self.assertEqual([(f["box_2d"], f["placement"]) for f in r["figures"]],
                         [([100.0, 200.0, 500.0, 800.0], "after_choices"), ([0.0, 0.0, 10.0, 10.0], "after_stem")])
        self.assertEqual(r["uncertain"], [{"where": "stem 첫 문단", "reason": "smudged"}])
        self.assertEqual(r["unsupported_block"], "box")

    def test_single_backslash_json_is_recovered(self):
        # 모델이 역슬래시를 한 번만 쓴 JSON: \l·\s·\c 등은 JSON에서 잘못된 이스케이프라 먼저 살려야 한다
        raw = '{"stem":[{"inlines":[{"t":"math","v":null,"latex":"x \\le \\sqrt{2} \\\\ y"}]}],"choices":null}'
        self.assertEqual(parse_read_json(raw)["stem"][0]["inlines"][0]["latex"], "x \\le \\sqrt{2} \\ y"
                         if False else "x \\le \\sqrt{2} \\\\ y".replace("\\\\ y", "\\ y"))

    def test_bad_outputs_raise(self):
        for bad in ("not json", "[]", json.dumps({"stem": "x"}), json.dumps({"stem": [{"inlines": [{"t": "image"}]}]}),
                    json.dumps({"stem": [{"inlines": [{"t": "math", "latex": None}]}]}),
                    json.dumps({"stem": [para(T("a"))], "choices": "x"}), ""):
            with self.assertRaises(ReadParseError):
                parse_read_json(bad)


class ReadCropTest(unittest.TestCase):
    def test_calls_once_with_filled_prompt_and_normalizes(self):
        out = json.dumps(doc([para(T("점 x 에 대하여 "), M("\x0crac{1}{2}"))]))
        c = FakeClient(out)
        obj, usage, fixed = read_crop(c, "m-read", png(2000, 1400))
        model, image, prompt, schema, limits = c.calls[0]
        self.assertEqual((len(c.calls), model, prompt, schema), (1, "m-read", load_prompt(), READ_SCHEMA))
        self.assertEqual(Image.open(io.BytesIO(image)).size, (1000, 700))
        self.assertEqual(limits.temperature, 0.0)
        self.assertEqual(fixed, 2)   # 변수 x 분리 + 이스케이프 복구
        self.assertEqual([(i["t"], i["v"] or i["latex"]) for i in obj["stem"][0]["inlines"]],
                         [("text", "점 "), ("math", "x"), ("text", " 에 대하여 "), ("math", "\\frac{1}{2}")])
        self.assertEqual(usage.input_tokens, 900)

    def test_small_crop_is_not_enlarged(self):
        c = FakeClient(json.dumps(doc([para(T("가"))])))
        read_crop(c, "m", png(600, 300))
        self.assertEqual(Image.open(io.BytesIO(c.calls[0][1])).size, (600, 300))

    def test_errors_propagate(self):
        with self.assertRaises(LlmError):
            read_crop(FakeClient(error=LlmError("timeout")), "m", png(500, 500))
        with self.assertRaises(ReadParseError):
            read_crop(FakeClient("not json"), "m", png(500, 500))

    def test_schema_requires_all_top_level_fields(self):
        self.assertEqual(READ_SCHEMA["required"], ["stem", "choices", "figures", "uncertain", "unsupported_block"])
        self.assertTrue(READ_SCHEMA["properties"]["choices"]["nullable"])
        self.assertEqual(READ_SCHEMA["properties"]["stem"]["items"]["properties"]["inlines"]["items"]["required"],
                         ["t", "v", "latex"])


if __name__ == "__main__":
    unittest.main()
