# -*- coding: utf-8 -*-
"""把扁平的 NEU 六类图片整理成训练清单与网站样例。

源目录默认：D:\\Users\\许展睿\\Pictures\\images
文件名形如 crazing_1.jpg、pitted_surface_1.jpg、rolled-in_scale_1.jpg。

输出：
    datasets/neu_split.json         训练/验证清单（80/20，按类别分层，MD5 去重）
    datasets/vision/neu/*.jpg       每类 20 张、共 120 张网站样例
    datasets/vision/neu/labels.json 样例的真值类别

用法：
    python tools/prepare_neu_samples.py
    python tools/prepare_neu_samples.py --source "D:/data/neu"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = Path(r"D:\Users\许展睿\Pictures\images")
OUT_SAMPLES = REPO / "datasets" / "vision" / "neu"
OUT_SPLIT = REPO / "datasets" / "neu_split.json"

CLASS_LABELS = {
    "crazing": "龟裂（网状裂纹）",
    "inclusion": "夹杂",
    "patches": "斑块",
    "pitted": "麻点",
    "rolled-in": "氧化皮压入",
    "scratches": "划痕",
}

# 源文件名前缀 → 项目类别名（longest first，避免短前缀抢先匹配）
SOURCE_PREFIXES = [
    ("rolled-in_scale", "rolled-in"),
    ("pitted_surface", "pitted"),
    ("crazing", "crazing"),
    ("inclusion", "inclusion"),
    ("patches", "patches"),
    ("scratches", "scratches"),
]


def classify(path: Path) -> str | None:
    stem = path.stem.lower()
    for prefix, label in SOURCE_PREFIXES:
        if stem == prefix or stem.startswith(prefix + "_"):
            return label
    return None


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="准备 NEU 训练清单与网站样例")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--per-class", type=int, default=20)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    source = Path(args.source)
    if not source.is_dir():
        raise SystemExit(f"源目录不存在：{source}")

    files = sorted(
        p for p in source.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    by_class: dict[str, list[Path]] = {label: [] for label in CLASS_LABELS}
    skipped = []
    for path in files:
        label = classify(path)
        if label is None:
            skipped.append(path.name)
            continue
        by_class[label].append(path)

    total = sum(len(v) for v in by_class.values())
    print(f"扫描 {len(files)} 张，识别 {total} 张，跳过 {len(skipped)} 张")
    if skipped:
        print("跳过示例：", skipped[:8])

    # MD5 去重：同一内容只保留文件名排序最靠前的一张
    unique_by_class: dict[str, list[Path]] = {}
    duplicate_count = 0
    for label, paths in by_class.items():
        seen = set()
        unique = []
        for path in paths:
            key = md5(path)
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
            unique.append(path)
        unique_by_class[label] = unique
    print(
        f"完全重复 {duplicate_count} 张，去重后各类：",
        {k: len(v) for k, v in unique_by_class.items()},
    )

    rng = random.Random(args.seed)
    items = []
    for label, paths in unique_by_class.items():
        shuffled = paths[:]
        rng.shuffle(shuffled)
        cut = max(1, int(round(len(shuffled) * args.val_ratio)))
        val = shuffled[:cut]
        train = shuffled[cut:]
        for path in train:
            items.append({"file": path.name, "class": label, "split": "train"})
        for path in val:
            items.append({"file": path.name, "class": label, "split": "val"})
        print(f"  {label:10s} train={len(train):3d} val={len(val):3d}")

    OUT_SPLIT.parent.mkdir(parents=True, exist_ok=True)
    OUT_SPLIT.write_text(
        json.dumps(
            {
                "source_root": str(source),
                "seed": args.seed,
                "val_ratio": args.val_ratio,
                "classes": list(CLASS_LABELS),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"训练清单：{OUT_SPLIT}")

    # 每类等间距抽 20 张，复制成规范文件名
    if OUT_SAMPLES.exists():
        shutil.rmtree(OUT_SAMPLES)
    OUT_SAMPLES.mkdir(parents=True, exist_ok=True)
    samples = []
    for label, paths in unique_by_class.items():
        ordered = sorted(paths)
        count = min(args.per_class, len(ordered))
        for index in range(count):
            pick = ordered[round(index * (len(ordered) - 1) / max(count - 1, 1))]
            target = OUT_SAMPLES / f"{label}_{index + 1:03d}.jpg"
            shutil.copyfile(pick, target)
            samples.append(
                {
                    "file": target.name,
                    "class": label,
                    "label": CLASS_LABELS[label],
                    "source": pick.name,
                }
            )
    samples.sort(key=lambda item: item["file"])
    (OUT_SAMPLES / "labels.json").write_text(
        json.dumps({"classes": CLASS_LABELS, "samples": samples}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"网站样例：{OUT_SAMPLES}（{len(samples)} 张）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
