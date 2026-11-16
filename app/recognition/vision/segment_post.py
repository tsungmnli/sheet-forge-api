"""B5-2b-1: 분할 LLM 출력 -> 문제 칸 (순수 로직. 이미지·LLM 호출 없음). 설계 5.2의 1·2·4·5·6번.
가장자리 맞춤(3번)은 이미지가 필요해서 B5-2b-3에서 붙인다.
좌표: LLM은 0~1000 [ymin,xmin,ymax,xmax], 이 모듈 안팎은 0~1 비율 [x0,y0,x1,y1]."""
import json
import math
import re

from ..ports import SegmentDraft

MIN_AREA = 0.005     # 페이지 면적의 0.5% 미만 칸은 버린다
MERGE_RATIO = 0.5    # 겹침이 작은 쪽 면적의 50%를 넘으면 합친다


class SegmentParseError(ValueError):
    """kind: not_json | bad_shape. 메시지에는 종류만 담는다(응답 내용 없음)."""


def _loads(text: str):
    s = (text or "").strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", s, re.S)
    if m:
        s = m.group(1)
    try:
        return json.loads(s)
    except ValueError:
        raise SegmentParseError("not_json") from None


def _box(v):
    """0~1000 [ymin,xmin,ymax,xmax] -> 0~1 (x0,y0,x1,y1), 0~1로 클램프. 잘못되면 None."""
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        return None
    try:
        ymin, xmin, ymax, xmax = (float(x) for x in v)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(x) for x in (ymin, xmin, ymax, xmax)):
        return None

    def c(x):
        return min(max(x / 1000.0, 0.0), 1.0)

    x0, y0, x1, y1 = c(xmin), c(ymin), c(xmax), c(ymax)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _number(v):
    """번호는 모델 값을 그대로 쓴다. 없으면 None. 우리가 만들지 않는다."""
    if v is None or isinstance(v, bool):
        return None
    s = str(v).strip()
    return s or None


def union_box(*boxes):
    bs = [b for b in boxes if b is not None]
    if not bs:
        return None
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def _area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


def _overlap(a, b):
    """겹친 폭·높이(없으면 0)."""
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])), max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _clip(sub, box):
    """하위 영역(선택지·그림)을 문제 칸 안으로 자른다. 비면 None."""
    if sub is None:
        return None
    x0, y0, x1, y1 = max(sub[0], box[0]), max(sub[1], box[1]), min(sub[2], box[2]), min(sub[3], box[3])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def parse_problems(text: str) -> list:
    """LLM 출력(JSON 문자열) -> [{"number","box","choices","figure"}]. box는 본문·선택지·그림의 합집합(설계 5.2의 6번)."""
    data = _loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("problems"), list):
        raise SegmentParseError("bad_shape")
    out = []
    for it in data["problems"]:
        if not isinstance(it, dict):
            continue
        box, choices, figure = _box(it.get("box_2d")), _box(it.get("choices_box_2d")), _box(it.get("figure_box_2d"))
        whole = union_box(box, choices, figure)
        if whole is None:
            continue
        out.append({"number": _number(it.get("number")), "box": whole, "choices": choices, "figure": figure})
    return out


def _merge(a, b):
    box = union_box(a["box"], b["box"])
    return {"number": a["number"] or b["number"], "box": box,
            "choices": union_box(a["choices"], b["choices"]), "figure": union_box(a["figure"], b["figure"])}


def _resize(it, box):
    it["box"] = box
    it["choices"], it["figure"] = _clip(it["choices"], box), _clip(it["figure"], box)


def _resolve_overlaps(items: list) -> list:
    """겹침이 크면 합치고, 작으면 경계를 겹친 구간의 가운데로 맞춘다(설계 5.2의 2번)."""
    items = list(items)
    while True:
        changed = False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                dx, dy = _overlap(a["box"], b["box"])
                inter = dx * dy
                if inter <= 0:
                    continue
                if inter > MERGE_RATIO * min(_area(a["box"]), _area(b["box"])):
                    items[i] = _merge(a, b)
                    del items[j]
                    changed = True
                    break
                ab, bb = a["box"], b["box"]
                if dy <= dx:    # 위아래로 조금 겹침 -> y 경계를 가운데로
                    up, down = (a, b) if (ab[1] + ab[3]) <= (bb[1] + bb[3]) else (b, a)
                    mid = (max(up["box"][1], down["box"][1]) + min(up["box"][3], down["box"][3])) / 2
                    nu, nd = (*up["box"][:3], mid), (down["box"][0], mid, *down["box"][2:])
                else:           # 좌우로 조금 겹침 -> x 경계를 가운데로
                    up, down = (a, b) if (ab[0] + ab[2]) <= (bb[0] + bb[2]) else (b, a)
                    mid = (max(up["box"][0], down["box"][0]) + min(up["box"][2], down["box"][2])) / 2
                    nu, nd = (up["box"][0], up["box"][1], mid, up["box"][3]), (mid, *down["box"][1:])
                if nu[2] > nu[0] and nu[3] > nu[1] and nd[2] > nd[0] and nd[3] > nd[1]:
                    _resize(up, nu)
                    _resize(down, nd)
                    changed = True
        if not changed:
            return items


def _reading_order(items: list) -> list:
    """칸 중심의 x로 열을 묶고(2단 편집), 열은 왼쪽부터, 열 안은 위에서 아래로(설계 5.2의 4번)."""
    cols = []   # [x0, x1, members]
    for it in sorted(items, key=lambda t: t["box"][0] + t["box"][2]):
        cx = (it["box"][0] + it["box"][2]) / 2
        for col in cols:
            if col[0] <= cx <= col[1]:
                col[0], col[1] = min(col[0], it["box"][0]), max(col[1], it["box"][2])
                col[2].append(it)
                break
        else:
            cols.append([it["box"][0], it["box"][2], [it]])
    cols.sort(key=lambda c: c[0])
    return [m for c in cols for m in sorted(c[2], key=lambda t: (t["box"][1], t["box"][0]))]


def _r(b):
    return None if b is None else tuple(round(v, 4) for v in b)


def segments_from_llm(text: str) -> list:
    """LLM 출력 -> 읽는 순서의 SegmentDraft 목록. 칸이 0개면 빈 목록(호출 쪽이 열 분할 폴백을 쓴다)."""
    items = [it for it in parse_problems(text) if _area(it["box"]) >= MIN_AREA]
    items = _reading_order(_resolve_overlaps(items))
    return [SegmentDraft(bbox=_r(it["box"]), number=it["number"], choices_bbox=_r(it["choices"]),
                         figure_bbox=_r(it["figure"])) for it in items]
