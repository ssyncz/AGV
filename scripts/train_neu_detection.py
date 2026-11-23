"""训练 NEU 六类缺陷检测器（YOLOv8n），一次输出"框 + 类别"。

前置：
    python scripts/prepare_neu_detection_dataset.py --src <数据集根目录> --dst runs/neu_yolo

用法：
    python scripts/train_neu_detection.py --data runs/neu_yolo/data.yaml --epochs 60

产物：
    runs/neu_yolo_runs/train/weights/best.pt   → 后端 services_detector 会自动发现
    runs/neu_yolo_runs/train/results.csv       → 逐 epoch 曲线
"""
from __future__ import annotations

import argparse
import json
import os


def main() -> int:
    parser = argparse.ArgumentParser(description="训练 NEU 缺陷检测器")
    parser.add_argument("--data", default=os.path.join("runs", "neu_yolo", "data.yaml"))
    parser.add_argument("--model", default="yolov8n.pt", help="预训练权重或 yaml")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--device", default="0", help="0=第一块 GPU，cpu=CPU")
    parser.add_argument("--optimizer", default="AdamW")
    parser.add_argument("--lr0", type=float, default=0.001)
    parser.add_argument("--patience", type=int, default=30)
    parser.add_argument("--close-mosaic", type=int, default=20)
    parser.add_argument("--degrees", type=float, default=5.0)
    parser.add_argument("--translate", type=float, default=0.1)
    parser.add_argument("--scale", type=float, default=0.5)
    parser.add_argument("--fliplr", type=float, default=0.5)
    parser.add_argument("--mixup", type=float, default=0.0)
    parser.add_argument("--mosaic", type=float, default=1.0)
    parser.add_argument("--cache", action="store_true")
    parser.add_argument("--project", default=os.path.join("runs", "neu_yolo_runs"))
    parser.add_argument("--name", default="train")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not os.path.isfile(args.data):
        raise SystemExit(f"找不到数据集配置：{args.data}（先跑 prepare_neu_detection_dataset.py）")

    from ultralytics import YOLO

    project = os.path.abspath(args.project)
    model = YOLO(args.model)
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        project=project,
        name=args.name,
        exist_ok=True,
        seed=args.seed,
        optimizer=args.optimizer,
        lr0=args.lr0,
        patience=args.patience,
        cos_lr=True,
        close_mosaic=args.close_mosaic,
        degrees=args.degrees,
        translate=args.translate,
        scale=args.scale,
        fliplr=args.fliplr,
        mixup=args.mixup,
        mosaic=args.mosaic,
        cache=args.cache,
    )

    best = os.path.join(project, args.name, "weights", "best.pt")
    print(f"\n最佳权重：{best}（存在：{os.path.isfile(best)}）")

    if not os.path.isfile(best):
        raise SystemExit(f"训练结束但未找到最佳权重：{best}")
    best_model = YOLO(best)
    metrics = best_model.val(data=args.data, imgsz=args.imgsz, batch=args.batch,
                             device=args.device, split="val", verbose=False)
    per_class = {}
    for index, class_id in enumerate(metrics.box.ap_class_index):
        class_id = int(class_id)
        per_class[best_model.names[class_id]] = {
            "precision": round(float(metrics.box.p[index]), 4),
            "recall": round(float(metrics.box.r[index]), 4),
            "mAP50": round(float(metrics.box.ap50[index]), 4),
            "mAP50-95": round(float(metrics.box.ap[index]), 4),
        }
    payload = {
        "mAP50": round(float(metrics.box.map50), 4),
        "mAP50-95": round(float(metrics.box.map), 4),
        "precision": round(float(metrics.box.mp), 4),
        "recall": round(float(metrics.box.mr), 4),
        "per_class": per_class,
        "model": args.model,
        "epochs": args.epochs,
        "imgsz": args.imgsz,
    }
    print("验证集：", json.dumps(payload, ensure_ascii=False))
    with open(os.path.join(project, args.name, "val_metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
