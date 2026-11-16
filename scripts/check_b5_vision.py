"""B5-1 육안 확인용: 사진을 보정하거나(기본) 그림을 정리해서(--figure) 결과 파일을 저장합니다.

sheet-forge-api 폴더에 scripts/check_b5_vision.py로 두고 실행합니다.
  uv run python scripts/check_b5_vision.py 사진1.jpg 사진2.heic            # 보정
  uv run python scripts/check_b5_vision.py --figure 그림1.png 그림2.jpg     # 그림 정리
  uv run python scripts/check_b5_vision.py --rotate 90 사진.jpg            # 90도 단위 회전(시계 방향)
결과는 smoke/b5/ (.gitignore에 들어 있음, --out으로 바꿀 수 있음)에 저장됩니다.
  <이름>_corners.jpg    입력에 찾은 꼭짓점을 그린 그림(초록: 찾음, 빨강: 못 찾아 전체 사용)
  <이름>_corrected.jpg  보정본(JPEG 품질 85)
  <이름>_clean.png      정리한 그림(과제거면 만들지 않고 "원본 사용"이라고 출력)
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.recognition.vision import correct  # noqa: E402
from app.recognition.vision.decode import DecodeError, decode_image, encode_jpeg  # noqa: E402
from app.recognition.vision.figure_clean import FigureCleaner  # noqa: E402


def check_photo(path: Path, out: Path, rotation: int):
    im = decode_image(path.read_bytes())
    t0 = time.time()
    res = correct.correct_page(im, rotation=rotation)
    ms = (time.time() - t0) * 1000

    # 꼭짓점 확인용: correct_page와 같은 축소·회전을 거친 입력에 사각형을 그린다
    rgb = np.ascontiguousarray(np.array(correct.downscale(im)))
    if rotation:
        rgb = np.ascontiguousarray(np.rot90(rgb, k=-(rotation // 90) % 4))
    h, w = rgb.shape[:2]
    pts = np.array([(x * w, y * h) for x, y in res.corners], np.int32)
    color = (0, 200, 0) if res.found else (230, 0, 0)
    cv2.polylines(rgb, [pts], True, color, max(3, max(h, w) // 300))
    Image.fromarray(rgb).save(out / f"{path.stem}_corners.jpg", quality=85)
    (out / f"{path.stem}_corrected.jpg").write_bytes(encode_jpeg(res.image, 85))
    state = "꼭짓점 찾음" if res.found else "꼭짓점 못 찾음 → 전체 사용 + 기울기 보정"
    print(f"{path.name}: {state}, 보정본 {res.image.size[0]}x{res.image.size[1]}, {ms:.0f}ms")


def check_figure(path: Path, out: Path):
    t0 = time.time()
    res = FigureCleaner().clean(path.read_bytes())
    ms = (time.time() - t0) * 1000
    if res.clean is None:
        print(f"{path.name}: 정리본 없음(과제거 또는 빈 그림) → 원본 그림 사용, {ms:.0f}ms")
        return
    (out / f"{path.stem}_clean.png").write_bytes(res.clean)
    print(f"{path.name}: 정리본 저장, {ms:.0f}ms")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--figure", action="store_true", help="입력을 그림 크롭으로 보고 정리한다")
    ap.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270))
    ap.add_argument("--out", type=Path, default=Path("smoke/b5"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    for f in a.files:
        try:
            check_figure(f, a.out) if a.figure else check_photo(f, a.out, a.rotate)
        except (DecodeError, OSError) as e:
            print(f"{f.name}: 실패({type(e).__name__}: {e})")
    print(f"저장 위치: {a.out}")


if __name__ == "__main__":
    main()
