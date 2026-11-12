# -*- coding: utf-8 -*-
"""视觉检测 —— 缺陷检测（定位 + 分类）

用一个 YOLOv8n 检测器一次给出"缺陷在哪里 + 是什么缺陷"，
替代原来"工件识别（只定位、不分类）"和"缺陷类型识别（只分类、不定位）"两条分离的链路。

权重查找顺序：
    models/neu_yolo.pt  →  runs/vision/neu_yolo.pt  →  runs/neu_yolo_runs/train/weights/best.pt

训练数据：E 盘 NEU 六类标注（1800 张 200×200），按文件名前缀重写类别后训练，
脚本见 scripts 之外的独立训练流程（runs/neu_yolo/data.yaml）。
"""
from __future__ import annotations

import os
import time

import cv2
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEIGHT_CANDIDATES = (
    os.path.join(PROJECT_ROOT, "models", "neu_yolo.pt"),
    os.path.join(PROJECT_ROOT, "runs", "vision", "neu_yolo.pt"),
    os.path.join(PROJECT_ROOT, "runs", "neu_yolo_runs", "train", "weights", "best.pt"),
)

CLASS_NAMES = ("crazing", "inclusion", "patches", "pitted_surface", "rolled-in_scale", "scratches")
CLASS_LABELS_ZH = {
    "crazing": "龟裂",
    "inclusion": "夹杂",
    "patches": "斑块",
    "pitted_surface": "麻点",
    "rolled-in_scale": "氧化皮压入",
    "scratches": "划痕",
}
CLASS_COLORS = {
    "crazing": (64, 128, 255),
    "inclusion": (96, 200, 96),
    "patches": (220, 160, 60),
    "pitted_surface": (180, 120, 240),
    "rolled-in_scale": (60, 180, 220),
    "scratches": (80, 90, 235),
}

DEFAULTS = {
    "conf": 0.25,
    "iou": 0.45,
    "imgsz": 320,
    "max_det": 30,
    "device": "auto",
}

_model = None
_model_path = None
_model_device = None


def _resolve_device(device: str) -> str:
    if device and device not in ("auto", ""):
        return device
    try:
        import torch

        return "0" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"


def find_weights() -> str | None:
    for path in WEIGHT_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def status() -> dict:
    weights = find_weights()
    payload = {
        "available": bool(weights),
        "weights": weights,
        "classes": list(CLASS_NAMES),
        "class_labels": CLASS_LABELS_ZH,
        "model": "YOLOv8n（NEU 六类缺陷，输入 320）",
    }
    return payload


def _merged(params: dict | None) -> dict:
    merged = dict(DEFAULTS)
    for key, value in (params or {}).items():
        if value is None or value == "":
            continue
        if key in {"conf", "iou"}:
            merged[key] = max(0.01, min(float(value), 0.99))
        elif key in {"imgsz", "max_det"}:
            merged[key] = max(64, min(int(float(value)), 1280))
        elif key == "device":
            merged[key] = str(value)
    return merged


def _get_model(params: dict):
    global _model, _model_path, _model_device
    weights = find_weights()
    if not weights:
        raise RuntimeError(
            "未找到缺陷检测权重。先训练：\n"
            "  python -c \"from ultralytics import YOLO; YOLO('yolov8n.pt').train(data=runs/neu_yolo/data.yaml, imgsz=320, epochs=60)\"\n"
            "或把 best.pt 放到 models/neu_yolo.pt"
        )
    device = _resolve_device(params.get("device", "auto"))
    if _model is not None and _model_path == weights and _model_device == device:
        return _model
    try:
        from ultralytics import YOLO
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"ultralytics 不可用：{type(exc).__name__}: {exc}") from exc

    model = YOLO(weights)
    try:
        model.to("cuda" if device not in ("cpu", "") else "cpu")
    except Exception:  # noqa: BLE001
        device = "cpu"
    _model, _model_path, _model_device = model, weights, device
    return _model


def detect_defects(image_bgr: np.ndarray, params: dict | None = None) -> dict:
    """对整图做缺陷检测，返回每个缺陷的类别 / 置信度 / 外接框。"""
    resolved = _merged(params)
    model = _get_model(resolved)
    height, width = image_bgr.shape[:2]
    started = time.perf_counter()
    results = model.predict(
        source=image_bgr,
        imgsz=int(resolved["imgsz"]),
        conf=float(resolved["conf"]),
        iou=float(resolved["iou"]),
        max_det=int(resolved["max_det"]),
        device=resolved.get("device") if resolved.get("device") not in (None, "", "auto") else None,
        verbose=False,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    objects: list[dict] = []
    class_counts: dict[str, int] = {}
    if results:
        boxes = results[0].boxes
        names = results[0].names or {}
        if boxes is not None and len(boxes):
            for index, box in enumerate(boxes):
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
                cls_id = int(box.cls[0].item()) if box.cls is not None else -1
                name = str(names.get(cls_id, cls_id))
                conf = float(box.conf[0].item()) if box.conf is not None else 0.0
                x, y = int(round(x1)), int(round(y1))
                w, h = max(1, int(round(x2 - x1))), max(1, int(round(y2 - y1)))
                objects.append({
                    "index": index + 1,
                    "class": name,
                    "label": CLASS_LABELS_ZH.get(name, name),
                    "confidence": round(conf, 4),
                    "bbox": [x, y, w, h],
                    "area": float(w * h),
                })
                class_counts[name] = class_counts.get(name, 0) + 1

    objects.sort(key=lambda item: item["confidence"], reverse=True)
    for index, item in enumerate(objects, start=1):
        item["index"] = index

    return {
        "objects": objects,
        "count": len(objects),
        "class_counts": class_counts,
        "elapsed_ms": elapsed_ms,
        "params": resolved,
        "width": width,
        "height": height,
        "model": status()["model"],
        "weights": find_weights(),
    }


def annotate_defects(image_bgr: np.ndarray, analysis: dict) -> np.ndarray:
    """把检测框和"类别 置信度"标签画到图上（顶部留一条信息栏）。"""
    image = image_bgr.copy()
    height, width = image.shape[:2]
    header = 30 if width >= 240 else 22
    canvas = np.zeros((height + header, width, 3), dtype=np.uint8)
    canvas[header:] = image
    canvas[:header] = (18, 26, 22)
    cv2.putText(
        canvas, f"objects: {analysis['count']}", (8, header - 9),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55 if width >= 240 else 0.42, (245, 252, 248), 1, cv2.LINE_AA,
    )
    thickness = max(1, int(round(max(width, height) / 320)))
    for item in analysis["objects"]:
        x, y, w, h = item["bbox"]
        color = CLASS_COLORS.get(item["class"], (200, 200, 200))
        cv2.rectangle(canvas, (x, y + header), (x + w, y + h + header), color, thickness)
        text = f"{item['class']} {item['confidence']:.2f}"
        scale = 0.42 if width >= 240 else 0.32
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        ty = max(header + 12, y + header - 4)
        cv2.rectangle(canvas, (x, ty - th - 4), (x + tw + 6, ty), color, -1)
        cv2.putText(
            canvas, text, (x + 3, ty - 3),
            cv2.FONT_HERSHEY_SIMPLEX, scale, (16, 24, 20), 1, cv2.LINE_AA,
        )
    return canvas
