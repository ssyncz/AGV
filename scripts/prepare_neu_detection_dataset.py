"""把 YOLO 格式的 NEU 六类缺陷标注整理成本项目可训练的数据集。

背景：原始标注（E 盘的 图像数据/images + labels）里，框的类别 id 与图片前缀并不一致
（例如 crazing 图里有 0/1/4 三类框）。NEU 数据集是"一图一类"，因此这里用文件名前缀
重写每个框的类别，得到干净的 6 类标注。

用法：
    python scripts/prepare_neu_detection_dataset.py \
        --src E:/下载文件/图像数据 \
        --dst runs/neu_yolo \
        --val-ratio 0.15

输出目录结构（可被 ultralytics 直接消费）：
    runs/neu_yolo/{images,labels}/{train,val} + data.yaml
"""
from __future__ import annotations

import argparse
import os
import random
import shutil
from collections import Counter

CLASSES = ("crazing", "inclusion", "patches", "pitted_surface", "rolled-in_scale", "scratches")
CLASS_ID = {name: i for i, name in enumerate(CLASSES)}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def prefix_of(filename: str) -> str:
    stem = os.path.splitext(filename)[0]
    prefix = stem.rsplit("_", 1)[0]
    if prefix in CLASS_ID:
        return prefix
    for name in sorted(CLASS_ID, key=len, reverse=True):
        if stem.startswith(name):
            return name
    return prefix


def main() -> int:
    parser = argparse.ArgumentParser(description="整理 NEU 六类缺陷检测数据集")
    parser.add_argument("--src", required=True, help="含 images/ 与 labels/ 的数据集根目录")
    parser.add_argument("--dst", default=os.path.join("runs", "neu_yolo"), help="输出目录")
    parser.add_argument("--val-ratio", type=float, default=0.15, help="验证集比例")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    src_images = os.path.join(args.src, "images")
    src_labels = os.path.join(args.src, "labels")
    if not os.path.isdir(src_images):
        raise SystemExit(f"缺少 images 目录：{src_images}")

    names = sorted(f for f in os.listdir(src_images) if os.path.splitext(f)[1].lower() in IMAGE_EXTS)
    if not names:
        raise SystemExit("源图片为空")

    for split in ("train", "val"):
        for kind in ("images", "labels"):
            os.makedirs(os.path.join(args.dst, kind, split), exist_ok=True)

    rng = random.Random(args.seed)
    rng.shuffle(names)
    val_cut = int(len(names) * args.val_ratio)
    split_of = {name: ("val" if i < val_cut else "train") for i, name in enumerate(names)}

    stats: Counter = Counter()
    boxes = 0
    for name in names:
        prefix = prefix_of(name)
        if prefix not in CLASS_ID:
            stats[f"skip:{prefix}"] += 1
            continue
        cls = CLASS_ID[prefix]
        label_name = os.path.splitext(name)[0] + ".txt"
        lines = []
        src_label = os.path.join(src_labels, label_name)
        if os.path.isfile(src_label):
            with open(src_label, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) != 5:
                        continue
                    try:
                        cx, cy, w, h = (float(v) for v in parts[1:])
                    except ValueError:
                        continue
                    if w <= 0 or h <= 0:
                        continue
                    lines.append(f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
        if not lines:
            stats[f"no_box:{prefix}"] += 1
            continue
        split = split_of[name]
        shutil.copy2(os.path.join(src_images, name), os.path.join(args.dst, "images", split, name))
        with open(os.path.join(args.dst, "labels", split, label_name), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        stats[split] += 1
        boxes += len(lines)

    yaml_lines = [
        f"path: {os.path.abspath(args.dst).replace(os.sep, '/')}",
        "train: images/train",
        "val: images/val",
        "",
        f"nc: {len(CLASSES)}",
        "names:",
    ] + [f"  {i}: {name}" for i, name in enumerate(CLASSES)]
    with open(os.path.join(args.dst, "data.yaml"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(yaml_lines) + "\n")

    print(f"输出：{os.path.abspath(args.dst)}")
    print(f"训练 {stats['train']} 张 / 验证 {stats['val']} 张，共 {boxes} 个框")
    print(f"类别：{', '.join(CLASSES)}")
    for key in sorted(k for k in stats if ":" in k):
        print(f"  {key}: {stats[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
