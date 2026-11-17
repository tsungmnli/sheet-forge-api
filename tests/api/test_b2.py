"""B2: 문제 칸·문제 API, 읽기 작업자, 그림, 읽기 한도. DB 통합 테스트는 SHEET_FORGE_TEST_DATABASE_URL이 있을 때만 돈다.
복사 위치: tests/test_b2.py"""
import io
import os
import struct
import unittest
import zlib
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from app.api.errors import ApiError
from app.api.main import create_app
from app.api.problem_logic import analyze, merge_figures, normalize_content, preview, preview_tex
from app.api.schemas import ContentIn
from app.api.settings import Settings
from app.db.database import Database
from app.recognition.fake import FakeFigureCleaner, FakePageProcessor, FakeRecognizer
from app.recognition.imaging import crop_region, figure_page_box
from app.storage.images import MemoryImageStore
from app.worker.main import run_once

TEST_URL = os.environ.get("SHEET_FORGE_TEST_DATABASE_URL", "")
ROOT = Path(__file__).resolve().parent.parent.parent
BAD_MATH = r"\foo"   # 알 수 없는 명령 → 변환 불가


def make_png(w=40, h=30):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes((200, 200, 220)) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def doc(*inlines):
    return {"stem": [{"type": "paragraph", "inlines": list(inlines)}], "choices": {"items": [], "layout": "auto"},
            "figures": []}


def T(v):
    return {"t": "text", "v": v}


def M(latex, **kw):
    return {"t": "math", "latex": latex, **kw}


class UnitTest(unittest.TestCase):
    def test_math_check_endpoint(self):
        c = TestClient(create_app(Settings()))
        r = c.post("/math/check", json={"items": [{"latex": "x^2"}, {"latex": BAD_MATH}, {"latex": " "}]})
        self.assertEqual(r.status_code, 200)
        res = r.json()["results"]
        self.assertEqual([x["status"] for x in res], ["ok", "unsupported", "unsupported"])
        self.assertGreater(res[0]["est_width"], 0)
        self.assertIsNone(res[1]["est_width"])
        self.assertNotIn("script", res[0])
        too_many = c.post("/math/check", json={"items": [{"latex": "x"}] * 201})
        self.assertEqual(too_many.status_code, 422)

    def test_openapi_has_b2_routes(self):
        paths = create_app(Settings()).openapi()["paths"]
        for p in ("/pages/{page_id}/segments/{segment_id}", "/pages/{page_id}/segments",
                  "/exams/{exam_id}/segments/mark", "/exams/{exam_id}/read", "/exams/{exam_id}/problems",
                  "/problems/{pid}", "/problems/{pid}/content", "/problems/{pid}/confirm",
                  "/problems/{pid}/reopen", "/problems/{pid}/revert", "/problems/{pid}/reread",
                  "/problems/{pid}/neighbors", "/problems/{pid}/figures",
                  "/problems/{pid}/figures/{fid}/region", "/problems/{pid}/figures/{fid}", "/math/check"):
            self.assertIn(p, paths)

    def test_analyze(self):
        hints, blockers, has = analyze(doc(T("가"), M(BAD_MATH), M("x^2", conf=0.5)))
        self.assertTrue(has)
        self.assertEqual([(b["path"], b["code"]) for b in blockers], [("stem/0/inlines/1", "MATH_UNSUPPORTED")])
        self.assertIn({"path": "stem/0/inlines/2", "kind": "low_confidence"}, hints)
        self.assertFalse(analyze(doc(T("  ")))[2])
        self.assertEqual(analyze(doc(M(" ")))[1][0]["code"], "MATH_UNSUPPORTED")   # 빈 수식도 막는다

    def test_preview_tex(self):
        self.assertEqual(preview_tex(doc(T("값 "), M(r"\frac{1}{2}"), T("이다"))), r"값 $\frac{1}{2}$이다")
        self.assertEqual(preview_tex(doc(T("가" * 98), M(r"\frac{1}{10}"))), "가" * 98 + "…")

    def test_preview(self):
        self.assertEqual(preview(doc(T("a  b"), M("x^2"))), "a bx^2")
        long = preview(doc(T("가" * 150)))
        self.assertTrue(long.endswith("…") and len(long) == 101)

    def test_normalize_content_rejects_bad_input(self):
        with self.assertRaises(ApiError) as cm:
            normalize_content(ContentIn.model_validate(doc({"t": "bogus"})))
        self.assertEqual(cm.exception.status, 422)
        with self.assertRaises(ApiError) as cm:
            normalize_content(ContentIn.model_validate(doc({"t": "image", "ref": "img_nope"})))
        self.assertEqual((cm.exception.status, cm.exception.code), (422, "FIGURE_REF_INVALID"))
        ok = normalize_content(ContentIn.model_validate(doc({"t": "image", "ref": "img_ok"})),
                               [{"id": "fig_1", "raw_ref": "img_ok", "clean_ref": None}])
        self.assertEqual(len(ok["figures"]), 1)   # 서버가 가진 그림은 요청에서 빠져도 지워지지 않는다

    def test_merge_figures(self):
        stored = [{"id": "fig_1", "raw_ref": "a", "clean_ref": "b", "use": "clean", "placement": "after_stem",
                   "width_mm": 60}]
        out = merge_figures([{"id": "fig_1", "use": "raw", "width_mm": 80}], stored)
        self.assertEqual((out[0]["use"], out[0]["width_mm"], out[0]["raw_ref"]), ("raw", 80, "a"))
        for bad in ({"id": "fig_x"}, {"id": "fig_1", "raw_ref": "zzz"}):
            with self.assertRaises(ApiError) as cm:
                merge_figures([bad], stored)
            self.assertEqual(cm.exception.code, "FIGURE_REF_INVALID")
        with self.assertRaises(ApiError):
            merge_figures([{"id": "fig_1", "width_mm": 1}], stored)
        with self.assertRaises(ApiError):
            merge_figures([{"id": "fig_1", "use": "weird"}], stored)

    def test_imaging(self):
        data, ctype, box = crop_region(make_png(40, 30), [0, 0, 0.5, 0.5], 0.0, "PNG")
        self.assertEqual(ctype, "image/png")
        self.assertEqual(Image.open(io.BytesIO(data)).size, (20, 15))
        self.assertEqual(box, [0.0, 0.0, 0.5, 0.5])
        _, ctype, box = crop_region(make_png(40, 30), [0.2, 0.2, 0.4, 0.4], 0.1)
        self.assertEqual(ctype, "image/jpeg")
        self.assertAlmostEqual(box[0], 0.1)
        self.assertAlmostEqual(box[2], 0.5)
        got = figure_page_box([0.2, 0.2, 0.6, 0.6], [0.5, 0.5, 1.0, 1.0])
        for g, w in zip(got, [0.4, 0.4, 0.6, 0.6]):
            self.assertAlmostEqual(g, w)

    def test_fake_recognizer(self):
        r = FakeRecognizer().read(b"", "high")
        self.assertEqual(r.meta, {"engine": "fake", "tier": "high"})
        self.assertEqual(len(r.content["choices"]["items"]), 5)


class Boom:
    def read(self, crop, tier="default"):
        raise RuntimeError("boom")


class DeletingRecognizer(FakeRecognizer):
    """읽는 도중 사용자가 문제를 지우는 상황."""

    def __init__(self, fn):
        self.fn = fn

    def read(self, crop, tier="default"):
        self.fn()
        return super().read(crop, tier)


@unittest.skipUnless(TEST_URL, "SHEET_FORGE_TEST_DATABASE_URL 없음 (DB 통합 테스트 건너뜀)")
class FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        with mock.patch.dict(os.environ, {"SHEET_FORGE_DATABASE_URL": TEST_URL}):
            command.upgrade(cfg, "head")
        cls.db = Database(TEST_URL, "", 2, 3)

    @classmethod
    def tearDownClass(cls):
        cls.db.dispose()

    def setUp(self):
        with self.db.session() as s:
            s.execute(text("TRUNCATE jobs, problems, read_usage, segments, pages, exams CASCADE"))
            s.commit()
        self.store = MemoryImageStore()

    # ---- 헬퍼 ----
    def _client(self, owner="o1", **settings):
        return TestClient(create_app(Settings(database_url=TEST_URL, default_owner_id=owner, **settings),
                                     store=self.store))

    def _work(self, n=1, recognizer=None, **kw):
        for _ in range(n):
            self.assertTrue(run_once(self.db, self.store, FakePageProcessor(),
                                     recognizer=recognizer or FakeRecognizer(), cleaner=FakeFigureCleaner(), **kw))

    def _setup(self, n_pick=0, **settings):
        """시험지 1건 + 사진 1장(문제 칸 6개) 처리 완료, 앞에서 n_pick개 고름."""
        self.c = self._client(**settings)
        exam = self.c.post("/exams", json={}).json()
        r = self.c.post(f"/exams/{exam['id']}/pages", files=[("files", ("p.png", make_png(40, 30), "image/png"))])
        self.assertEqual(r.status_code, 202)
        page_id = r.json()["items"][0]["id"]
        self._work(1)
        segs = self.c.get(f"/pages/{page_id}").json()["segments"]
        self.assertEqual(len(segs), 6)
        for s in segs[:n_pick]:
            self.assertEqual(self._pick(page_id, s["id"]).status_code, 200)
        return exam["id"], page_id, segs

    def _pick(self, page_id, seg_id, marked=True):
        return self.c.patch(f"/pages/{page_id}/segments/{seg_id}", json={"marked": marked})

    def _read(self, exam_id, **body):
        r = self.c.post(f"/exams/{exam_id}/read", json=body or None)
        self.assertEqual(r.status_code, 202, r.text)
        return r.json()

    def _problem_ids(self, exam_id, state=None):
        q = f"?state={state}" if state else ""
        return [i["problem_id"] for i in self.c.get(f"/exams/{exam_id}/problems{q}").json()["items"]
                if i["problem_id"]]

    def _get(self, pid):
        r = self.c.get(f"/problems/{pid}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["ETag"], f'"{r.json()["version"]}"')
        return r.json()

    def _put(self, pid, content, version=None, points=None):
        v = version if version is not None else self._get(pid)["version"]
        return self.c.put(f"/problems/{pid}/content", json={"content": content, "points": points},
                          headers={"If-Match": f'"{v}"'})

    def _confirm(self, pid, version=None):
        v = version if version is not None else self._get(pid)["version"]
        return self.c.post(f"/problems/{pid}/confirm", headers={"If-Match": f'"{v}"'})

    def _read_one(self):
        """칸 1개를 읽어 needs_review까지. (exam_id, page_id, segs, problem_id)"""
        exam_id, page_id, segs = self._setup(1)
        self._read(exam_id)
        self._work(1)
        pid = self._problem_ids(exam_id)[0]
        self.assertEqual(self._get(pid)["status"], "needs_review")
        return exam_id, page_id, segs, pid

    # ---- 칸 고르기 ----
    def test_pick_and_unpick(self):
        exam_id, page_id, segs = self._setup()
        r = self._pick(page_id, segs[0]["id"])
        self.assertEqual((r.json()["picked_count"], r.json()["exam_picked_count"]), (1, 1))
        self.assertTrue(r.json()["segment"]["marked"])
        r = self._pick(page_id, segs[0]["id"], False)
        self.assertEqual((r.status_code, r.json()["picked_count"]), (200, 0))
        self.assertEqual(self._pick(page_id, "seg_nope").status_code, 404)

    def test_mark_many(self):
        exam_id, page_id, segs = self._setup()
        url = f"/exams/{exam_id}/segments/mark"
        r = self.c.post(url, json={"marked": True})
        self.assertEqual((r.json()["changed"], r.json()["picked_count"]), (6, 6))
        self.assertEqual(self.c.post(url, json={"marked": True}).json()["changed"], 0)
        r = self.c.post(url, json={"marked": False, "segment_ids": [segs[0]["id"], segs[1]["id"]]})
        self.assertEqual((r.json()["changed"], r.json()["picked_count"]), (2, 4))
        r = self.c.post(url, json={"marked": False, "page_id": page_id})
        self.assertEqual((r.json()["changed"], r.json()["picked_count"]), (4, 0))
        both = self.c.post(url, json={"marked": True, "page_id": page_id, "segment_ids": [segs[0]["id"]]})
        self.assertEqual(both.status_code, 422)

    def test_unpick_blocked_when_problem_exists(self):
        exam_id, page_id, segs = self._setup(2)
        self._read(exam_id)
        self.assertEqual(self._pick(page_id, segs[0]["id"], False).status_code, 409)
        self.assertEqual(self._pick(page_id, segs[0]["id"], False).json()["error"]["code"], "SEGMENT_HAS_PROBLEM")
        r = self.c.post(f"/exams/{exam_id}/segments/mark", json={"marked": False})
        self.assertEqual((r.json()["changed"], r.json()["skipped"], r.json()["picked_count"]), (0, 2, 2))

    def test_put_segments_keep_add_remove(self):
        exam_id, page_id, segs = self._setup(1)            # 첫 칸만 고른 상태
        keep = {"id": segs[0]["id"], "bbox": [0.1, 0.1, 0.5, 0.3], "number": "07"}
        new = {"bbox": [0.5, 0.5, 0.9, 0.9]}
        r = self.c.put(f"/pages/{page_id}/segments", json={"segments": [keep, new]})
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()["segments"]
        self.assertEqual(len(out), 2)
        self.assertEqual((out[0]["id"], out[0]["number"], out[0]["marked"]), (segs[0]["id"], "07", True))
        self.assertFalse(out[1]["marked"])
        self.assertEqual(r.json()["picked_count"], 1)
        bad = self.c.put(f"/pages/{page_id}/segments", json={"segments": [{"bbox": [0.5, 0.5, 0.5, 0.5]}]})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.c.put(f"/pages/{page_id}/segments",
                                    json={"segments": [{"id": "seg_nope", "bbox": [0.1, 0.1, 0.5, 0.5]}]}).status_code, 422)

    def test_put_segments_cannot_remove_read_segment(self):
        exam_id, page_id, segs = self._setup(1)
        self._read(exam_id)
        r = self.c.put(f"/pages/{page_id}/segments", json={"segments": [{"bbox": [0.1, 0.1, 0.5, 0.5]}]})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "SEGMENT_HAS_PROBLEM"))

    # ---- 읽기 ----
    def test_read_flow(self):
        exam_id, page_id, segs = self._setup(2)
        res = self._read(exam_id)
        self.assertEqual((res["requested"], res["skipped"]), (2, []))
        self.assertTrue(all(p["status"] == "recognizing" for p in res["problems"]))
        self.assertIsNotNone(res["poll_after_ms"])
        pid = res["problems"][0]["id"]
        p = self._get(pid)
        self.assertEqual((p["status"], p["checks"]["can_confirm"]), ("recognizing", False))
        self.assertEqual(self._put(pid, doc(T("가")), version=p["version"]).status_code, 409)   # 읽는 중
        self.assertEqual(self._put(pid, doc(T("가")), version=p["version"]).json()["error"]["code"], "PROBLEM_BUSY")
        items = self.c.get(f"/exams/{exam_id}/problems").json()["items"]
        self.assertEqual([i["state"] for i in items], ["recognizing"] * 2)
        self._work(2)
        p = self._get(pid)
        self.assertEqual(p["status"], "needs_review")
        self.assertIn("가짜 읽기", p["content"]["stem"][0]["inlines"][0]["v"])
        self.assertEqual(len(p["content"]["choices"]["items"]), 5)
        self.assertTrue(p["ocr"]["has_recognized"])
        self.assertNotIn("recognized", p)
        self.assertTrue(p["checks"]["can_confirm"])
        self.assertIn("low_confidence", [h["kind"] for h in p["hints"]])
        self.assertTrue(p["source"]["crop_url"])
        self.assertIsNotNone(self.store.get(p["source"]["crop_url"].rsplit("/", 1)[-1]))
        again = self._read(exam_id)                                  # 이미 읽은 칸은 건너뜀
        self.assertEqual(again["requested"], 0)
        by_state = self.c.get(f"/exams/{exam_id}/problems?state=needs_review").json()["items"]
        self.assertEqual(len(by_state), 2)
        self.assertIsNone(self.c.get(f"/exams/{exam_id}/problems").json()["poll_after_ms"])

    def test_read_explicit_segment_ids_and_reasons(self):
        exam_id, page_id, segs = self._setup(1)
        res = self._read(exam_id, segment_ids=[segs[0]["id"], segs[1]["id"], "seg_nope", segs[0]["id"]])
        self.assertEqual(res["requested"], 1)
        reasons = {s["segment_id"]: s["reason"] for s in res["skipped"]}
        self.assertEqual(reasons, {segs[1]["id"]: "not_picked", "seg_nope": "not_found"})
        again = self._read(exam_id, segment_ids=[segs[0]["id"]])
        self.assertEqual((again["requested"], again["skipped"][0]["reason"]), (0, "already_read"))
        self.assertEqual(self.c.get(f"/exams/{exam_id}/problems").json()["items"][0]["state"], "recognizing")

    def test_not_read_items_listed(self):
        exam_id, page_id, segs = self._setup(3)
        items = self.c.get(f"/exams/{exam_id}/problems").json()["items"]
        self.assertEqual([(i["state"], i["problem_id"]) for i in items], [("not_read", None)] * 3)
        self.assertEqual(self.c.get(f"/exams/{exam_id}/problems?state=confirmed").json()["items"], [])
        self.assertEqual(self.c.get(f"/exams/{exam_id}/problems?state=weird").status_code, 422)

    def test_read_limits(self):
        exam_id, page_id, segs = self._setup(2, daily_read_limit=1)
        r = self.c.post(f"/exams/{exam_id}/read")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (429, "READ_LIMIT"))
        self.assertEqual(self._problem_ids(exam_id), [])             # 일부만 읽히지 않는다
        exam_id, page_id, segs = self._setup(1, max_read_batch=0)
        r = self.c.post(f"/exams/{exam_id}/read")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "TOO_MANY_SEGMENTS"))

    def test_reread_costs_double(self):
        exam_id, page_id, segs = self._setup(1, daily_read_limit=3)
        self._read(exam_id)                                         # 1
        self._work(1)
        pid = self._problem_ids(exam_id)[0]
        r = self.c.post(f"/problems/{pid}/reread")                # +2 = 3
        self.assertEqual((r.status_code, r.json()["status"]), (202, "recognizing"))
        self.assertEqual(self.c.post(f"/problems/{pid}/reread").status_code, 409)   # 읽는 중
        self._work(1)
        self.assertEqual(self._get(pid)["status"], "needs_review")
        r = self.c.post(f"/problems/{pid}/reread")                # 한도 초과
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (429, "READ_LIMIT"))
        self.assertEqual(self._get(pid)["status"], "needs_review")

    # ---- 자동 저장·확인·상태 전이 ----
    def test_version_conflict_and_required(self):
        *_, pid = self._read_one()
        p = self._get(pid)
        ok = self._put(pid, doc(T("바꿈")), version=p["version"], points=3.5)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual((ok.json()["version"], ok.json()["points"]), (p["version"] + 1, 3.5))
        self.assertEqual(ok.headers["ETag"], f'"{p["version"] + 1}"')
        stale = self._put(pid, doc(T("또")), version=p["version"])
        self.assertEqual((stale.status_code, stale.json()["error"]["code"]), (412, "VERSION_CONFLICT"))
        r = self.c.put(f"/problems/{pid}/content", json={"content": doc(T("x")), "points": None})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (428, "VERSION_REQUIRED"))
        stale_confirm = self._confirm(pid, version=p["version"])
        self.assertEqual(stale_confirm.status_code, 412)

    def test_confirm_blocked_then_allowed(self):
        *_, pid = self._read_one()
        r = self._put(pid, doc(T("값은 "), M(BAD_MATH)))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["checks"]["can_confirm"])
        self.assertEqual(r.json()["checks"]["blockers"][0]["path"], "stem/0/inlines/1")
        c = self._confirm(pid)
        self.assertEqual((c.status_code, c.json()["error"]["code"]), (409, "MATH_UNSUPPORTED"))
        self.assertEqual(c.json()["error"]["details"][0]["path"], "stem/0/inlines/1")
        self.assertEqual(self._get(pid)["status"], "needs_review")
        self._put(pid, doc(T("값은 "), M("x+1")))
        c = self._confirm(pid)
        self.assertEqual((c.status_code, c.json()["status"]), (200, "confirmed"))
        self.assertEqual(self._confirm(pid, version=c.json()["version"]).status_code, 200)   # 두 번 눌러도 같은 결과
        self.assertEqual(self._get(pid)["version"], c.json()["version"])
        r = self._put(pid, doc(T("고침")))
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "PROBLEM_CONFIRMED"))
        ro = self.c.post(f"/problems/{pid}/reopen")
        self.assertEqual((ro.status_code, ro.json()["status"]), (200, "needs_review"))
        self.assertEqual(self._put(pid, doc(T("고침"))).status_code, 200)
        self.assertEqual(self.c.post(f"/problems/{pid}/reopen").status_code, 409)   # 확인 완료가 아님

    def test_confirm_empty_problem(self):
        *_, pid = self._read_one()
        self._put(pid, doc(T("  ")))
        p = self._get(pid)
        self.assertFalse(p["checks"]["can_confirm"])
        self.assertEqual(p["checks"]["blockers"][0]["code"], "EMPTY_PROBLEM")
        c = self._confirm(pid)
        self.assertEqual((c.status_code, c.json()["error"]["code"]), (422, "EMPTY_PROBLEM"))

    def test_warn_math_does_not_block(self):
        *_, pid = self._read_one()
        self._put(pid, doc(T("값 "), M("x^2", conf=0.2)))
        self.assertEqual(self._confirm(pid).status_code, 200)

    def test_revert_restores_recognized(self):
        *_, pid = self._read_one()
        first = self._get(pid)["content"]
        self._put(pid, doc(T("직접 고침")))
        r = self.c.post(f"/problems/{pid}/revert")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["content"]["stem"], first["stem"])
        self.assertEqual(r.json()["content"]["choices"], first["choices"])

    def test_delete_problem_and_unpick(self):
        exam_id, page_id, segs, pid = self._read_one()
        self.assertEqual(self.c.delete(f"/problems/{pid}").status_code, 204)
        self.assertEqual(self.c.get(f"/problems/{pid}").status_code, 404)
        self.assertEqual(self.c.delete(f"/problems/{pid}").status_code, 404)
        self.assertEqual(self._pick(page_id, segs[0]["id"], False).status_code, 200)   # 이제 해제할 수 있다
        self._pick(page_id, segs[0]["id"])
        self.assertEqual(self._read(exam_id)["requested"], 1)                           # 다시 읽기 시작 가능

    def test_neighbors(self):
        exam_id, page_id, segs = self._setup(3)
        self._read(exam_id)
        self._work(3)
        ids = self._problem_ids(exam_id)
        self.assertEqual(len(ids), 3)
        r = self.c.get(f"/problems/{ids[1]}/neighbors?exam_id={exam_id}&state=needs_review")
        self.assertEqual(r.json(), {"index": 2, "total": 3, "prev_id": ids[0], "next_id": ids[2]})
        self.assertEqual(self._confirm(ids[0]).status_code, 200)
        r = self.c.get(f"/problems/{ids[1]}/neighbors?state=needs_review")
        self.assertEqual((r.json()["index"], r.json()["total"], r.json()["prev_id"]), (1, 2, None))
        self.assertEqual(self.c.get(f"/problems/{ids[1]}/neighbors?exam_id=exam_other").status_code, 404)

    def test_other_owner_sees_nothing(self):
        exam_id, page_id, segs, pid = self._read_one()
        other = self._client(owner="o2")
        self.assertEqual(other.get(f"/problems/{pid}").status_code, 404)
        self.assertEqual(other.post(f"/exams/{exam_id}/read").status_code, 404)
        self.assertEqual(other.patch(f"/pages/{page_id}/segments/{segs[0]['id']}", json={"marked": False}).status_code, 404)

    # ---- 그림 ----
    def test_figure_lifecycle(self):
        *_, pid = self._read_one()
        body = {"bbox": [0.1, 0.1, 0.5, 0.5], "placement": "after_stem", "width_mm": 60}
        r = self.c.post(f"/problems/{pid}/figures", json=body)
        self.assertEqual(r.status_code, 202, r.text)
        fig = r.json()["content"]["figures"][0]
        self.assertEqual((fig["state"], fig["raw_ref"], fig["clean_ref"]), ("processing", None, None))
        self._work(1)
        fig = self._get(pid)["content"]["figures"][0]
        self.assertEqual((fig["state"], fig["use"]), ("ready", "clean"))
        self.assertIsNotNone(self.store.get(fig["raw_ref"]))
        self.assertIsNotNone(self.store.get(fig["clean_ref"]))
        # 그림은 서버가 관리한다: 본문 저장에서 빠져도 지워지지 않고, 사용 방식·너비는 바꿀 수 있다
        r = self._put(pid, doc(T("그림 있음")))
        self.assertEqual(len(r.json()["content"]["figures"]), 1)
        content = doc(T("그림 있음"))
        content["figures"] = [{"id": fig["id"], "use": "raw", "width_mm": 80}]
        r = self._put(pid, content)
        self.assertEqual((r.json()["content"]["figures"][0]["use"], r.json()["content"]["figures"][0]["width_mm"]),
                         ("raw", 80))
        # 범위 고치기 → 다시 처리, 예전 이미지는 정리됨
        old = (fig["raw_ref"], fig["clean_ref"])
        r = self.c.put(f"/problems/{pid}/figures/{fig['id']}/region", json={"bbox": [0.2, 0.2, 0.6, 0.6]})
        self.assertEqual((r.status_code, r.json()["content"]["figures"][0]["state"]), (202, "processing"))
        self._work(1)
        new = self._get(pid)["content"]["figures"][0]
        self.assertEqual(new["state"], "ready")
        self.assertNotIn(new["raw_ref"], old)
        self.assertIsNone(self.store.get(old[0]))
        self.assertIsNone(self.store.get(old[1]))
        r = self.c.delete(f"/problems/{pid}/figures/{fig['id']}")
        self.assertEqual((r.status_code, r.json()["content"]["figures"]), (200, []))
        self.assertEqual(self.c.delete(f"/problems/{pid}/figures/{fig['id']}").status_code, 404)

    def test_figure_rejected_while_confirmed(self):
        *_, pid = self._read_one()
        self._confirm(pid)
        r = self.c.post(f"/problems/{pid}/figures", json={"bbox": [0.1, 0.1, 0.5, 0.5]})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "PROBLEM_CONFIRMED"))
        bad = self.c.post(f"/problems/{pid}/figures", json={"bbox": [0.5, 0.5, 0.5, 0.5]})
        self.assertIn(bad.status_code, (409, 422))

    def test_figure_clean_failure_falls_back_to_raw(self):
        *_, pid = self._read_one()
        self.c.post(f"/problems/{pid}/figures", json={"bbox": [0.1, 0.1, 0.5, 0.5]})

        class BadCleaner:
            def clean(self, raw):
                raise RuntimeError("cleaner down")

        self.assertTrue(run_once(self.db, self.store, FakePageProcessor(), recognizer=FakeRecognizer(),
                                 cleaner=BadCleaner()))
        fig = self._get(pid)["content"]["figures"][0]
        self.assertEqual((fig["state"], fig["use"], fig["clean_ref"]), ("ready", "raw", None))
        self.assertIsNotNone(self.store.get(fig["raw_ref"]))

    # ---- 작업자 ----
    def test_read_failure_marks_failed_and_can_reread(self):
        exam_id, page_id, segs = self._setup(1)
        self._read(exam_id)
        self._work(1, recognizer=Boom(), max_attempts=1)
        pid = self._problem_ids(exam_id)[0]
        p = self._get(pid)
        self.assertEqual(p["status"], "failed")
        self.assertEqual(self.c.get(f"/exams/{exam_id}/problems").json()["items"][0]["badges"], ["읽지 못했어요"])
        self.assertEqual(self._put(pid, doc(T("직접 입력"))).status_code, 200)       # 실패해도 직접 입력은 계속할 수 있다
        self.assertEqual(self._confirm(pid).json()["status"], "confirmed")
        self.assertEqual(self.c.post(f"/problems/{pid}/reopen").status_code, 200)
        r = self.c.post(f"/problems/{pid}/reread")
        self.assertEqual((r.status_code, r.json()["status"]), (202, "recognizing"))

    def test_problem_deleted_while_reading(self):
        exam_id, page_id, segs = self._setup(1)
        self._read(exam_id)
        pid = self._problem_ids(exam_id)[0]
        before = set(self.store.objects)
        rec = DeletingRecognizer(lambda: self.assertEqual(self.c.delete(f"/problems/{pid}").status_code, 204))
        self._work(1, recognizer=rec)
        self.assertEqual(self.c.get(f"/problems/{pid}").status_code, 404)
        self.assertEqual(set(self.store.objects), before)        # 만들다 만 크롭 이미지는 정리됨

    def test_reread_replaces_old_crop(self):
        *_, pid = self._read_one()
        crop1 = self._get(pid)["source"]["crop_url"].rsplit("/", 1)[-1]
        self.c.post(f"/problems/{pid}/reread")
        self._work(1)
        p = self._get(pid)
        crop2 = p["source"]["crop_url"].rsplit("/", 1)[-1]
        self.assertNotEqual(crop1, crop2)
        self.assertIsNone(self.store.get(crop1))
        self.assertIsNotNone(self.store.get(crop2))
        self.assertIn("(high)", p["content"]["stem"][0]["inlines"][0]["v"])


if __name__ == "__main__":
    unittest.main()
