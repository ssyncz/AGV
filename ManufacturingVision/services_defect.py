# -*- coding: utf-8 -*-
"""表面缺陷类型识别（NEU 热轧带钢 6 类）：crazing / inclusion / patches / pitted / rolled-in / scratches。

与「裂纹分割」互补：先判类型，再对线状类（crazing / scratches）做分割定位。
模型：小型 CNN（64×64 灰度，25 轮，测试准确率 0.989）。
"""
import json
import os

import cv2
import numpy as np

CLASSES = ["crazing", "inclusion", "patches", "pitted", "rolled-in", "scratches"]
CLASS_LABELS = {
    "crazing": "龟裂（网状裂纹）",
    "inclusion": "夹杂",
    "patches": "斑块",
    "pitted": "麻点",
    "rolled-in": "氧化皮压入",
    "scratches": "划痕",
}
SIZE = 64
_model = None
_weight = None


def find_weights():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in (
        os.path.join(here, "runs", "vision", "neu_cnn.pt"),
        os.path.join(here, "models", "neu_cnn.pt"),
    ):
        if os.path.exists(rel):
            return rel
    return None


def _build_net():
    import torch
    import torch.nn as nn

    class SmallNet(nn.Module):
        def __init__(self, n=len(CLASSES)):
            super().__init__()
            self.f = nn.Sequential(
                nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(), nn.MaxPool2d(2),
                nn.AdaptiveAvgPool2d(1),
            )
            self.c = nn.Linear(128, n)

        def forward(self, x):
            return self.c(self.f(x).flatten(1))

    return SmallNet()


def get_model(device="cpu"):
    global _model, _weight
    if _model is not None:
        return _model
    w = find_weights()
    if w is None:
        raise RuntimeError("未找到缺陷分类权重：runs/vision/neu_cnn.pt")
    import torch
    net = _build_net().to(device)
    net.load_state_dict(torch.load(w, map_location=device))
    net.eval()
    _model = net
    _weight = w
    return net


def available():
    try:
        import torch  # noqa: F401
        return find_weights() is not None
    except Exception:
        return False


def status():
    weights = find_weights()
    metrics = None
    if weights:
        metrics_path = os.path.splitext(weights)[0] + ".metrics.json"
        if os.path.isfile(metrics_path):
            try:
                with open(metrics_path, encoding="utf-8") as handle:
                    metrics = json.load(handle)
            except (OSError, ValueError):
                metrics = None
    return {
        "available": available(),
        "weights": weights,
        "classes": CLASSES,
        "class_labels": CLASS_LABELS,
        "model": "SmallCNN(64x64, 3 conv blocks)",
        "test_accuracy": (metrics or {}).get("best_val_accuracy"),
        "train_samples": (metrics or {}).get("train_samples"),
        "val_samples": (metrics or {}).get("val_samples"),
        "metrics": metrics,
    }


def classify_defect(image, device="cpu"):
    """对单张 BGR 图做缺陷类型识别，返回 top-1/top-3 与各类概率。"""
    import torch

    net = get_model(device)
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    x = (resized.astype(np.float32) / 255.0 - 0.5) / 0.5
    t = torch.from_numpy(x[None, None]).float().to(device)
    with torch.no_grad():
        prob = torch.softmax(net(t), dim=1)[0].cpu().numpy()

    order = np.argsort(prob)[::-1]
    top3 = [{"class": CLASSES[i], "label": CLASS_LABELS[CLASSES[i]],
             "probability": round(float(prob[i]), 4)} for i in order[:3]]
    best = CLASSES[int(order[0])]
    return {
        "task": "defect_classification",
        "model": "SmallCNN(64x64) · NEU 6类",
        "weights": _weight,
        "predicted_class": best,
        "predicted_label": CLASS_LABELS[best],
        "confidence": round(float(prob[order[0]]), 4),
        "top3": top3,
        "probabilities": {CLASSES[i]: round(float(prob[i]), 4) for i in range(len(CLASSES))},
        "is_line_like": best in ("crazing", "scratches"),
        "note": "线状类（crazing/scratches）建议再做裂纹分割定位；patches/pitted/inclusion 非线状",
    }
