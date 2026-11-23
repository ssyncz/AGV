# -*- coding: utf-8 -*-
"""训练 NEU 六类表面缺陷分类模型（SmallCNN，64×64 灰度）。

数据目录支持两种摆放方式（任选其一）::

    <data_root>/images/<class>/*.jpg          # 单目录，按类别分文件夹
    <data_root>/<class>/*.jpg                 # 直接按类别分文件夹

类别名必须是 services_defect.CLASSES 里的六个：
    crazing / inclusion / patches / pitted / rolled-in / scratches

用法::

    .\\venv\\Scripts\\python.exe scripts\\train_neu.py --data-root datasets/neu

输出：
    runs/vision/neu_cnn.pt              权重（供 services_defect 加载）
    runs/vision/neu_cnn.metrics.json    训练与验证指标
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ManufacturingVision.services_defect import CLASSES, SIZE, _build_net  # noqa: E402

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _class_dirs(root: Path) -> dict[str, Path]:
    """找到每个类别对应的目录，兼容 images/<class> 与 <class> 两种布局。"""
    candidates = [root / "images", root]
    for base in candidates:
        if not base.is_dir():
            continue
        found = {cls: base / cls for cls in CLASSES if (base / cls).is_dir()}
        if found:
            return found
    raise FileNotFoundError(
        f"在 {root} 下没有找到按类别命名的目录，期望 images/<class>/ 或 <class>/"
    )


def _collect(root: Path):
    """返回 [(路径, 类别下标)]，并按类别做可复现的训练/验证切分。"""
    dirs = _class_dirs(root)
    missing = [cls for cls in CLASSES if cls not in dirs]
    if missing:
        print(f"[提示] 缺少类别目录：{missing}，这些类别将不参与训练", file=sys.stderr)
    items = []
    for cls, directory in dirs.items():
        files = sorted(p for p in directory.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES)
        items.extend((p, CLASSES.index(cls)) for p in files)
    if not items:
        raise FileNotFoundError(f"{root} 下没有找到图片")
    return items


def split(items, val_ratio: float, seed: int):
    rng = random.Random(seed)
    by_class: dict[int, list] = {}
    for item in items:
        by_class.setdefault(item[1], []).append(item)
    train, val = [], []
    for label, group in by_class.items():
        rng.shuffle(group)
        cut = max(1, int(round(len(group) * val_ratio))) if len(group) > 1 else 0
        val.extend(group[:cut])
        train.extend(group[cut:])
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


class NEUDataset(Dataset):
    def __init__(self, items, transform):
        self.items = items
        self.transform = transform

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        path, label = self.items[index]
        image = Image.open(path).convert("L")
        return self.transform(image), label


def build_transforms():
    train_tf = transforms.Compose([
        transforms.Resize((SIZE + 8, SIZE + 8)),
        transforms.RandomCrop(SIZE),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(5),
        transforms.ToTensor(),
        transforms.Normalize((0.5,), (0.5,)),
    ])
    val_tf = transforms.Compose([
        transforms.Resize((SIZE, SIZE)),
        transforms.ToTensor(),
        transforms.Normalize((0.5,), (0.5,)),
    ])
    return train_tf, val_tf


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    correct = total = 0
    confusion = torch.zeros(len(CLASSES), len(CLASSES), dtype=torch.long)
    for images, labels in loader:
        images, labels = images.to(device), labels.to(device)
        pred = model(images).argmax(dim=1)
        correct += int((pred == labels).sum())
        total += int(labels.numel())
        for truth, guess in zip(labels.tolist(), pred.tolist()):
            confusion[truth, guess] += 1
    accuracy = correct / total if total else 0.0
    per_class = {}
    for index, name in enumerate(CLASSES):
        tp = int(confusion[index, index])
        support = int(confusion[index].sum())
        predicted = int(confusion[:, index].sum())
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        per_class[name] = {
            "support": support,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
        }
    return accuracy, per_class, confusion.tolist()


def _load_manifest(path: Path):
    """读取 prepare_neu_samples.py 生成的扁平训练清单。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    root = Path(payload["source_root"])
    train_items, val_items = [], []
    for item in payload.get("items", []):
        label = item.get("class")
        if label not in CLASSES:
            raise ValueError(f"清单里出现未知类别：{label}")
        image_path = root / item["file"]
        if not image_path.is_file():
            raise FileNotFoundError(f"清单中的图片不存在：{image_path}")
        bucket = train_items if item.get("split") == "train" else val_items
        bucket.append((image_path, CLASSES.index(label)))
    return root, train_items, val_items


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="训练 NEU 六类缺陷分类模型")
    parser.add_argument("--data-root", help="NEU 数据根目录（按类别分文件夹）")
    parser.add_argument("--manifest", help="prepare_neu_samples.py 生成的 neu_split.json")
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=str(REPO / "runs" / "vision" / "neu_cnn.pt"))
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args(argv)

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    device = torch.device(args.device)

    if args.manifest:
        source_root, train_items, val_items = _load_manifest(Path(args.manifest))
        print(f"使用清单 {args.manifest}，源目录 {source_root}")
    elif args.data_root:
        items = _collect(Path(args.data_root))
        train_items, val_items = split(items, args.val_ratio, args.seed)
        source_root = Path(args.data_root)
    else:
        parser.error("必须提供 --manifest 或 --data-root")
    print(f"训练 {len(train_items)} 张，验证 {len(val_items)} 张，设备 {device}")

    train_tf, val_tf = build_transforms()
    train_loader = DataLoader(NEUDataset(train_items, train_tf), batch_size=args.batch_size,
                              shuffle=True, num_workers=0)
    val_loader = DataLoader(NEUDataset(val_items, val_tf), batch_size=args.batch_size,
                            shuffle=False, num_workers=0)

    model = _build_net().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    best_accuracy = 0.0
    best_state = None
    for epoch in range(1, args.epochs + 1):
        model.train()
        running = 0.0
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            running += float(loss.item()) * labels.numel()
        accuracy, _, _ = evaluate(model, val_loader, device)
        print(f"epoch {epoch:02d}/{args.epochs}  loss={running / max(len(train_items), 1):.4f}"
              f"  val_acc={accuracy:.4f}")
        if accuracy >= best_accuracy:
            best_accuracy = accuracy
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(best_state or model.state_dict(), out)

    if best_state:
        model.load_state_dict(best_state)
    final_accuracy, per_class, confusion = evaluate(model, val_loader, device)
    metrics = {
        "dataset": str(source_root),
        "manifest": args.manifest,
        "train_samples": len(train_items),
        "val_samples": len(val_items),
        "epochs": args.epochs,
        "best_val_accuracy": round(best_accuracy, 4),
        "final_val_accuracy": round(final_accuracy, 4),
        "classes": CLASSES,
        "per_class": per_class,
        "confusion": confusion,
    }
    metrics_path = out.with_suffix(".metrics.json")
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"权重已保存：{out}")
    print(f"指标已保存：{metrics_path}")
    print(f"最佳验证准确率：{best_accuracy:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
