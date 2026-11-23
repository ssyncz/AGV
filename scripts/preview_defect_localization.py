"""为六类 NEU 样例生成红框定位预览拼图，供人工视觉验收。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ManufacturingVision.services import load_image  # noqa: E402
from ManufacturingVision.services_defect import classify_defect  # noqa: E402
from ManufacturingVision.services_defect_localization import (  # noqa: E402
    annotate_defect,
    locate_defect,
    rejection_decision,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成六类缺陷红框预览")
    parser.add_argument("--sample-dir", default=str(REPO / "datasets" / "vision" / "neu"))
    parser.add_argument("--out", default=str(REPO / "runs" / "vision" / "defect_preview.jpg"))
    args = parser.parse_args(argv)

    sample_dir = Path(args.sample_dir)
    representatives = {}
    for path in sorted(sample_dir.glob("*.jpg")):
        representative = path.name.split("_", 1)[0]
        representatives.setdefault(representative, path)

    tiles = []
    summary = []
    for expected_class, path in representatives.items():
        image = load_image(path)
        if image is None:
            continue
        result = classify_defect(image)
        gate = rejection_decision(result)
        if gate["uncertain"]:
            annotation = annotate_defect(
                image,
                verdict="uncertain",
                predicted_class=None,
                predicted_label=gate["raw_predicted_label"],
                confidence=gate["confidence"],
                objects=[],
            )
            boxes = []
        else:
            located = locate_defect(
                image,
                predicted_class=gate["raw_predicted_class"],
                confidence=gate["confidence"],
            )
            boxes = located["boxes"]
            annotation = annotate_defect(
                image,
                verdict="defect",
                predicted_class=gate["raw_predicted_class"],
                predicted_label=gate["raw_predicted_label"],
                confidence=gate["confidence"],
                objects=located["objects"],
            )
        annotation = cv2.resize(annotation, (320, 320), interpolation=cv2.INTER_AREA)
        cv2.putText(
            annotation,
            expected_class,
            (8, 314),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (20, 20, 20),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            annotation,
            expected_class,
            (8, 314),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        tiles.append(annotation)
        summary.append({
            "expected": expected_class,
            "raw_prediction": gate["raw_predicted_class"],
            "confidence": gate["confidence"],
            "uncertain": gate["uncertain"],
            "boxes": boxes,
        })

    if len(tiles) != 6:
        raise RuntimeError(f"需要六类样例，实际生成 {len(tiles)} 张预览。")
    rows = [np.hstack(tiles[index:index + 3]) for index in range(0, 6, 3)]
    contact_sheet = np.vstack(rows)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    success, encoded = cv2.imencode(".jpg", contact_sheet, [cv2.IMWRITE_JPEG_QUALITY, 94])
    if not success:
        raise RuntimeError("预览图编码失败。")
    encoded.tofile(str(output))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"预览拼图已保存：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
