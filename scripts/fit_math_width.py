"""수식 폭 추정 점검·재피팅 (README 6.7, 설계 10장).

갤러리 v1의 hangul_w(한글이 계산한 폭, HWPUNIT)와 convert()의 est_width_em을 비교한다.
우리가 방출하는 스크립트와 같은 표기(공백·`·~ 무시, 대소문자 무시)인 항목만 쓴다.

사용법 (sheet-forge-api/ 에서)
  python scripts/fit_math_width.py                 # 현재 상수의 오차만 보고
  python scripts/fit_math_width.py --fit           # 상수를 다시 맞추고 W 딕셔너리를 출력 (scipy 필요)
  python scripts/fit_math_width.py --fit --cv      # 5겹 교차검증으로 과적합 확인
  python scripts/fit_math_width.py --corpus 경로    # 코퍼스 위치 지정 (기본 tests/fixtures/math_gallery_v1_results.json)

--fit은 작게 추정하는 오차(줄바꿈을 놓침)를 2배로 벌점을 줘서 약간 크게 추정하는 쪽으로 맞춘다.
결과는 emit.py의 W에 직접 옮겨 적는다(SYM_W·FUNC_W는 기호·함수별 실측값이라 건드리지 않는다).
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.export.math import emit                      # noqa: E402
from app.export.math.convert import convert            # noqa: E402
from app.export.math.parser import Ctx, parse          # noqa: E402

DEFAULT_CORPUS = ROOT / "tests" / "fixtures" / "math_gallery_v1_results.json"


def _nz(s):
    return re.sub(r"[\s`~]+", "", s).lower()


def load_rows(path):
    """[(id, latex, 기준 폭 em, AST)] — 우리 방출 스크립트와 표기가 같은 ok 항목만."""
    rows = []
    for x in json.loads(Path(path).read_text(encoding="utf-8")):
        if x.get("verdict") != "ok" or not x.get("hangul_w"):
            continue
        r = convert(x["latex"], allow_documented=True)
        if r.ok and _nz(r.script) == _nz(x["script"]):
            rows.append((x["id"], x["latex"], x["hangul_w"] / 1000.0, parse(x["latex"], Ctx())))
    return rows


def rel_errors(rows):
    return [(emit.est_width(ast) - h) / h for _, _, h, ast in rows]


def report(title, rows):
    e = rel_errors(rows)
    n = len(e)
    print(f"[{title}] n={n}  평균오차 {sum(e)/n:+.1%}  평균절대 {sum(abs(v) for v in e)/n:.1%}  "
          f"최대절대 {max(abs(v) for v in e):.1%}  10%초과 과소 {sum(v < -0.1 for v in e)}  과대 {sum(v > 0.1 for v in e)}")


def worst(rows, k=8):
    e = rel_errors(rows)
    for (i, l, h, _), v in sorted(zip(rows, e), key=lambda t: -abs(t[1]))[:k]:
        print(f"  {i:6} 한글 {h:6.2f}  오차 {v:+.0%}  {l}")


def fit(rows, keys):
    import numpy as np
    from scipy.optimize import minimize

    x0 = np.array([emit.W[k] for k in keys])

    def loss(x):
        for k, v in zip(keys, x):
            emit.W[k] = float(v)
        e = np.array(rel_errors(rows))
        return float(np.mean(np.where(e < 0, 2.0, 1.0) * e ** 2))

    res = minimize(loss, x0, method="Powell", bounds=[(0.0, 3.0)] * len(keys), options={"xtol": 1e-3, "ftol": 1e-6})
    for k, v in zip(keys, res.x):
        emit.W[k] = float(v)
    return {k: round(float(v), 2) for k, v in zip(keys, res.x)}


def cross_validate(rows, keys, folds=5):
    import random
    idx = list(range(len(rows)))
    random.Random(0).shuffle(idx)
    base = dict(emit.W)
    out = []
    for f in range(folds):
        test = [rows[i] for i in idx[f::folds]]
        train = [rows[i] for i in idx if i not in set(idx[f::folds])]
        emit.W.update(base)
        fit(train, keys)
        out += [abs(v) for v in rel_errors(test)]
    emit.W.update(base)
    print(f"[교차검증 {folds}겹] 평균절대 {sum(out)/len(out):.1%}  최대절대 {max(out):.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--cv", action="store_true")
    a = ap.parse_args()

    rows = load_rows(a.corpus)
    if not rows:
        sys.exit("사용할 항목이 없음: 코퍼스 경로를 확인하세요.")
    report("현재", rows)
    worst(rows)
    if a.fit or a.cv:
        keys = list(emit.W)
        if a.cv:
            cross_validate(rows, keys)
        if a.fit:
            new = fit(rows, keys)
            report("재피팅 후", rows)
            worst(rows)
            print("\nW = " + json.dumps(new, ensure_ascii=False))


if __name__ == "__main__":
    main()
