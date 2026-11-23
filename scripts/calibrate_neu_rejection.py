"""校准 NEU 六类缺陷分类器的安全拒识阈值。

已知缺陷使用 datasets/neu_split.json 中验证集，跨域负样本使用 MT_Free 图片和
随机噪声。目标是：已知六类缺陷保留率 >= 95%，在此基础上最大化负样本拒识率。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AGV.settings")

import django  # noqa: E402

django.setup()

from ManufacturingVision.datasets import FREE_IMAGE_DIR  # noqa: E402
from ManufacturingVision.services_defect import classify_defect  # noqa: E402
from ManufacturingVision.services import load_image  # noqa: E402


def _known_validation_paths(manifest_path: Path) -> list[tuple[str, Path]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = Path(payload["source_root"])
    return [
        (item["class"], root / item["file"])
        for item in payload.get("items", [])
        if item.get("split") == "val" and (root / item["file"]).is_file()
    ]


def _score(image, tta=True):
    result = classify_defect(image, tta=tta)
    probabilities = sorted(result["probabilities"].values(), reverse=True)
    return (
        result["predicted_class"],
        float(probabilities[0]),
        float(probabilities[0] - probabilities[1]),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="校准 NEU 六类缺陷拒识阈值")
    parser.add_argument("--manifest", default=str(REPO / "datasets" / "neu_split.json"))
    parser.add_argument("--out", default=str(REPO / "runs" / "vision" / "neu_rejection.metrics.json"))
    parser.add_argument("--min-retention", type=float, default=0.95)
    args = parser.parse_args(argv)

    known_paths = _known_validation_paths(Path(args.manifest))
    if not known_paths:
        raise RuntimeError("没有找到 NEU 验证图片，请检查 manifest 与 source_root。")

    known_scores = []
    tta_correct = 0
    single_correct = 0
    for expected_class, path in known_paths:
        image = load_image(path)
        if image is not None:
            predicted, confidence, margin = _score(image, tta=True)
            known_scores.append((confidence, margin))
            tta_correct += int(predicted == expected_class)
            single_prediction, _, _ = _score(image, tta=False)
            single_correct += int(single_prediction == expected_class)

    ood_scores = []
    for path in sorted(FREE_IMAGE_DIR.glob("*")):
        image = load_image(path)
        if image is not None:
            _, confidence, margin = _score(image)
            ood_scores.append((confidence, margin))

    rng = np.random.default_rng(20261102)
    for _ in range(50):
        noise = rng.integers(0, 256, size=(256, 256), dtype=np.uint8)
        _, confidence, margin = _score(np.repeat(noise[:, :, None], 3, axis=2))
        ood_scores.append((confidence, margin))
    if not ood_scores:
        raise RuntimeError("没有可用的跨域负样本。")

    known = np.asarray(known_scores, dtype=np.float32)
    ood = np.asarray(ood_scores, dtype=np.float32)
    candidates = []
    for confidence_threshold in np.quantile(known[:, 0], np.linspace(0.0, 0.1, 41)):
        for margin_threshold in np.quantile(known[:, 1], np.linspace(0.0, 0.3, 61)):
            known_retention = float(
                np.mean(
                    (known[:, 0] >= confidence_threshold)
                    & (known[:, 1] >= margin_threshold)
                )
            )
            if known_retention < args.min_retention:
                continue
            ood_rejection = float(
                np.mean(
                    (ood[:, 0] < confidence_threshold)
                    | (ood[:, 1] < margin_threshold)
                )
            )
            candidates.append({
                "min_confidence": round(float(confidence_threshold), 4),
                "min_margin": round(float(margin_threshold), 4),
                "known_retention": round(known_retention, 4),
                "ood_rejection": round(ood_rejection, 4),
            })
    if not candidates:
        raise RuntimeError("无法在指定保留率下找到拒识阈值。")

    best = max(
        candidates,
        key=lambda item: (
            item["ood_rejection"],
            item["known_retention"],
            item["min_margin"],
        ),
    )
    payload = {
        **best,
        "known_samples": len(known_scores),
        "ood_samples": len(ood_scores),
        "single_view_accuracy": round(single_correct / max(len(known_scores), 1), 4),
        "tta_accuracy": round(tta_correct / max(len(known_scores), 1), 4),
        "target_known_retention": args.min_retention,
        "known_confidence_p05": round(float(np.quantile(known[:, 0], 0.05)), 4),
        "known_margin_p05": round(float(np.quantile(known[:, 1], 0.05)), 4),
        "note": (
            "MT_Free 与随机纹理仅作为跨域拒识参考，不代表正常钢材外部测试准确率。"
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"阈值指标已保存：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
