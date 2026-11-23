"""NEU 六类缺陷的近似定位与安全拒识。

分类模型只有图像级标签，没有缺陷框监督。因此本模块使用最后一层卷积特征的
Grad-CAM 作为“模型看到了哪里”的证据，再结合局部反差、黑帽/顶帽响应细化区域。
生成的框用于人工复核，不应解释为标注级检测精度。
"""
from __future__ import annotations

import cv2
import numpy as np

from .services_defect import CLASSES, CLASS_LABELS, SIZE, get_model
from .services import _limit_side, _vesselness_map

REJECTION_LABEL = "不属于6类缺陷或无缺陷，请人工复核"
REJECTION_REASON = "classification_confidence_or_margin_too_low"
# scripts/calibrate_neu_rejection.py 在 360 张 NEU 验证图上按 95% 已知缺陷
# 保留率校准；跨域负样本拒识率仅作为风险参考，不是正常钢材准确率。
MIN_CONFIDENCE = 0.6523
MIN_MARGIN = 0.3342
MAX_BOXES = 5
LINE_CLASSES = {"crazing", "scratches"}
BLOB_LOCALIZATION = {
    "inclusion": {"quantile": 0.93, "close_divisor": 24},
    "patches": {"quantile": 0.85, "close_divisor": 12},
    "pitted": {"quantile": 0.88, "close_divisor": 18},
    "rolled-in": {"quantile": 0.9, "close_divisor": 16},
}


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def rejection_decision(result: dict) -> dict:
    """根据 Top-1 置信度和 Top-1/Top-2 间隔判断是否安全拒识。"""
    probabilities = result.get("probabilities") or {}
    ordered = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    if len(ordered) < 2:
        confidence = float(result.get("confidence", 0.0))
        margin = 0.0
        best = result.get("predicted_class") or ""
    else:
        best, confidence = ordered[0]
        margin = float(confidence - ordered[1][1])
    reasons = []
    if confidence < MIN_CONFIDENCE:
        reasons.append("low_confidence")
    if margin < MIN_MARGIN:
        reasons.append("small_class_margin")
    uncertain = bool(reasons)
    return {
        "uncertain": uncertain,
        "reason": ",".join(reasons) or None,
        "raw_predicted_class": best,
        "raw_predicted_label": CLASS_LABELS.get(best, best),
        "confidence": round(float(confidence), 4),
        "margin": round(float(margin), 4),
        "min_confidence": MIN_CONFIDENCE,
        "min_margin": MIN_MARGIN,
    }


def _normalize(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    if values.size == 0:
        return values
    low, high = np.percentile(values, (2.0, 98.0))
    if high <= low + 1e-8:
        return np.zeros_like(values)
    return np.clip((values - low) / (high - low), 0.0, 1.0)


def _gradcam(image: np.ndarray, class_index: int, device: str = "cpu") -> np.ndarray:
    """对最终 8×8 卷积特征计算 Grad-CAM，并插值回原图尺寸。"""
    import torch

    model = get_model(device)
    gray = _gray(image)
    resized = cv2.resize(gray, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    tensor = (
        (resized.astype(np.float32) / 255.0 - 0.5) / 0.5
    )[None, None]
    tensor = torch.from_numpy(tensor).float().to(device).requires_grad_(True)

    model.zero_grad(set_to_none=True)
    features = model.f(tensor)
    features.retain_grad()
    logits = model.c(features.mean(dim=(2, 3)))
    logits[0, class_index].backward()

    gradients = features.grad.detach()[0]
    activations = features.detach()[0]
    weights = gradients.mean(dim=(1, 2))
    cam = torch.relu((weights[:, None, None] * activations).sum(dim=0))
    cam = cam.cpu().numpy().astype(np.float32)
    cam = _normalize(cam)
    height, width = gray.shape[:2]
    return cv2.resize(cam, (width, height), interpolation=cv2.INTER_CUBIC)


def _iou(left: list[int], right: list[int]) -> float:
    ax, ay, aw, ah = left
    bx, by, bw, bh = right
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


def _should_join_collinear(left: list[int], right: list[int]) -> bool:
    ax, ay, aw, ah = left
    bx, by, bw, bh = right
    x_overlap = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    y_overlap = max(0, min(ay + ah, by + bh) - max(ay, by))
    vertical_gap = max(0, max(ay, by) - min(ay + ah, by + bh))
    horizontal_gap = max(0, max(ax, bx) - min(ax + aw, bx + bw))
    same_column = x_overlap >= 0.45 * min(aw, bw) and vertical_gap <= max(12, 0.15 * max(ah, bh))
    same_row = y_overlap >= 0.45 * min(ah, bh) and horizontal_gap <= max(12, 0.15 * max(aw, bw))
    return same_column or same_row


def _merge_boxes(items: list[dict], *, join_collinear: bool = False) -> list[dict]:
    merged = list(items)
    changed = True
    while changed:
        changed = False
        for left_index in range(len(merged)):
            for right_index in range(left_index + 1, len(merged)):
                left, right = merged[left_index], merged[right_index]
                overlaps = _iou(left["box"], right["box"]) >= 0.3
                if not overlaps and join_collinear:
                    overlaps = _should_join_collinear(left["box"], right["box"])
                if not overlaps:
                    continue
                x1 = min(left["box"][0], right["box"][0])
                y1 = min(left["box"][1], right["box"][1])
                x2 = max(
                    left["box"][0] + left["box"][2],
                    right["box"][0] + right["box"][2],
                )
                y2 = max(
                    left["box"][1] + left["box"][3],
                    right["box"][1] + right["box"][3],
                )
                left["box"] = [x1, y1, x2 - x1, y2 - y1]
                left["score"] = max(left["score"], right["score"])
                merged.pop(right_index)
                changed = True
                break
            if changed:
                break
    return merged


def _fallback_box(response: np.ndarray) -> list[int]:
    threshold = float(np.quantile(response, 0.9))
    mask = (response >= threshold).astype(np.uint8) * 255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        height, width = response.shape[:2]
        return [0, 0, width, height]
    contour = max(contours, key=cv2.contourArea)
    return [int(value) for value in cv2.boundingRect(contour)]


def _union_box(boxes: list[list[int]]) -> list[int]:
    x1 = min(box[0] for box in boxes)
    y1 = min(box[1] for box in boxes)
    x2 = max(box[0] + box[2] for box in boxes)
    y2 = max(box[1] + box[3] for box in boxes)
    return [x1, y1, x2 - x1, y2 - y1]


def _line_candidates(image: np.ndarray, cam: np.ndarray) -> tuple[list[dict], float]:
    """检测明/暗细线并沿 Hough 线段聚合成连续红框。"""
    gray = _gray(image)
    height, width = gray.shape[:2]
    small, scale = _limit_side(gray, 1024)
    blurred = cv2.GaussianBlur(small, (3, 3), 0.7)
    dark = _vesselness_map(blurred, (1.0, 1.6, 2.4), 0.6)
    bright = _vesselness_map(255 - blurred, (1.0, 1.6, 2.4), 0.6)
    response = _normalize(np.maximum(dark, bright))
    short_side = min(small.shape[:2])
    threshold = max(0.025, float(np.quantile(response, 0.97)))
    mask = (response >= threshold).astype(np.uint8) * 255
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    )

    lines = cv2.HoughLinesP(
        mask,
        1,
        np.pi / 180,
        threshold=8,
        minLineLength=max(10, int(round(short_side * 0.05))),
        maxLineGap=max(3, int(round(short_side * 0.03))),
    )
    line_mask = np.zeros_like(mask)
    if lines is not None:
        thickness = max(3, int(round(short_side * 0.018)))
        for line in lines[:, 0]:
            x1, y1, x2, y2 = [int(value) for value in line]
            cv2.line(line_mask, (x1, y1), (x2, y2), 255, thickness, cv2.LINE_AA)
        line_mask = cv2.morphologyEx(
            line_mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
        )
    proposals = line_mask if np.count_nonzero(line_mask) else mask

    total, labels, stats, _ = cv2.connectedComponentsWithStats(proposals, 8)
    image_area = float(small.shape[0] * small.shape[1])
    cam_small = cv2.resize(cam, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_AREA)
    candidates = []
    for index in range(1, total):
        x, y, box_width, box_height, area = stats[index]
        area_ratio = float(area) / image_area
        if area_ratio < 0.00035 or area_ratio > 0.35:
            continue
        if max(box_width, box_height) < short_side * 0.055:
            continue
        component = labels == index
        line_score = float(response[component].mean())
        cam_score = float(cam_small[component].mean())
        length_score = min(1.0, max(box_width, box_height) / max(short_side * 0.35, 1))
        score = 0.7 * line_score + 0.2 * cam_score + 0.1 * length_score
        if x <= 1 or y <= 1 or x + box_width >= small.shape[1] - 1 or y + box_height >= small.shape[0] - 1:
            score *= 0.82
        candidates.append({
            "box": [
                int(round(x / scale)),
                int(round(y / scale)),
                int(round(box_width / scale)),
                int(round(box_height / scale)),
            ],
            "score": round(score, 4),
            "area_ratio": round(area_ratio, 6),
        })
    if not candidates:
        candidates = [{
            "box": _fallback_box(response),
            "score": round(float(response.max()), 4),
            "area_ratio": None,
        }]
        if scale != 1.0:
            candidates[0]["box"] = [
                int(round(value / scale)) for value in candidates[0]["box"]
            ]
    return candidates, 0.97


def _blob_candidates(
    image: np.ndarray,
    cam: np.ndarray,
    predicted_class: str,
) -> tuple[list[dict], float]:
    """提取暗色块状异常并合并为单个总体区域。"""
    config = BLOB_LOCALIZATION[predicted_class]
    gray = _gray(image)
    small, scale = _limit_side(gray, 1024)
    height, width = small.shape[:2]
    short_side = min(height, width)
    sigma = max(3.0, short_side / 18.0)
    background = cv2.GaussianBlur(small, (0, 0), sigmaX=sigma, sigmaY=sigma)
    signed_dark = _normalize(np.maximum(background.astype(np.float32) - small, 0))
    kernel_size = max(11, int(round(short_side / 10.0)) | 1)
    blackhat = cv2.morphologyEx(
        small,
        cv2.MORPH_BLACKHAT,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)),
    )
    response = np.maximum(
        signed_dark,
        _normalize(blackhat),
    )
    response = cv2.GaussianBlur(response, (0, 0), 1.2)
    threshold = max(
        0.035,
        float(np.quantile(response, config["quantile"])),
    )
    mask = (response >= threshold).astype(np.uint8) * 255
    close_size = max(
        5,
        int(round(short_side / float(config["close_divisor"]))) | 1,
    )
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size)),
    )
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )

    total, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    cam_small = cv2.resize(cam, (width, height), interpolation=cv2.INTER_AREA)
    image_area = float(width * height)
    components = []
    for index in range(1, total):
        x, y, box_width, box_height, area = stats[index]
        area_ratio = float(area) / image_area
        if area_ratio < 0.0005 or area_ratio > 0.65:
            continue
        component = labels == index
        size_factor = min(1.0, (area_ratio / 0.08) ** 0.5)
        score = (
            0.72 * float(response[component].mean()) * size_factor
            + 0.28 * float(cam_small[component].mean())
        )
        center_x = (x + box_width / 2.0) / max(width, 1)
        center_y = (y + box_height / 2.0) / max(height, 1)
        center_distance = min(
            1.0,
            ((center_x - 0.5) ** 2 + (center_y - 0.5) ** 2) ** 0.5 / 0.707,
        )
        score *= 1.0 - 0.55 * center_distance
        if (
            x <= 1
            or y <= 1
            or x + box_width >= width - 1
            or y + box_height >= height - 1
        ):
            score *= 0.2
        components.append({
            "box": [int(x), int(y), int(box_width), int(box_height)],
            "score": score,
            "area_ratio": area_ratio,
        })

    if not components:
        box = _fallback_box(response)
        components = [{
            "box": [int(round(value / scale)) for value in box],
            "score": round(float(response.max()), 4),
            "area_ratio": None,
        }]
        return components, float(config["quantile"])

    components.sort(key=lambda item: item["score"], reverse=True)
    best_score = components[0]["score"]
    dominant = [
        item for item in components
        if item["score"] >= max(0.04, best_score * 0.45)
    ][:MAX_BOXES]
    if predicted_class == "patches":
        central = [
            item for item in dominant
            if item["box"][0] > 1
            and item["box"][1] > 1
            and item["box"][0] + item["box"][2] < width - 1
            and item["box"][1] + item["box"][3] < height - 1
        ] or [dominant[0]]
        dominant = [{
            "box": _union_box([item["box"] for item in central]),
            "score": dominant[0]["score"],
            "area_ratio": round(
                sum(item["area_ratio"] or 0 for item in central), 6
            ),
        }]
    for item in dominant:
        item["box"] = [int(round(value / scale)) for value in item["box"]]
    return dominant, float(config["quantile"])


def locate_defect(
    image: np.ndarray,
    *,
    predicted_class: str,
    confidence: float,
    device: str = "cpu",
) -> dict:
    """生成最多 5 个红框候选；框坐标均位于原图范围内。"""
    class_index = CLASSES.index(predicted_class)
    cam = _gradcam(image, class_index, device=device)
    is_line = predicted_class in LINE_CLASSES
    # CNN 的特征图只有 8×8，直接融合会把纹理边缘放大成巨框。这里用局部反差
    # 生成可解释的候选区域，Grad-CAM 只负责参与候选排序。
    if is_line:
        candidates, quantile = _line_candidates(image, cam)
        method = "gradcam+dual_line+hough"
        response_height, response_width = _gray(image).shape[:2]
    else:
        candidates, quantile = _blob_candidates(image, cam, predicted_class)
        method = "gradcam+dark_region"
        response_height, response_width = _gray(image).shape[:2]

    candidates = sorted(
        candidates,
        key=lambda item: (item["score"], item["box"][2] * item["box"][3]),
        reverse=True,
    )
    candidates = _merge_boxes(candidates, join_collinear=is_line)
    if candidates:
        primary = candidates[0]
        best_score = primary["score"]
        dominant = [
            item for item in candidates
            if item["score"] >= max(0.08, best_score * 0.62)
        ]
        candidates = dominant or [primary]
    candidates = candidates[:MAX_BOXES]

    objects = []
    pad = max(3, int(round(min(response_width, response_height) * 0.02)))
    for item in candidates:
        x, y, box_width, box_height = item["box"]
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(response_width, x + box_width + pad)
        y2 = min(response_height, y + box_height + pad)
        objects.append({
            "label": predicted_class,
            "label_zh": CLASS_LABELS[predicted_class],
            "box": [x1, y1, x2 - x1, y2 - y1],
            "score": item["score"],
            "confidence": round(float(confidence), 4),
            "area_ratio": item["area_ratio"],
        })
    return {
        "boxes": [item["box"] for item in objects],
        "objects": objects,
        "method": method,
        "quantile": quantile,
    }


def annotate_defect(
    image: np.ndarray,
    *,
    verdict: str,
    predicted_class: str | None,
    predicted_label: str,
    confidence: float,
    objects: list[dict],
) -> np.ndarray:
    """在结果图绘制红框和可读标签。"""
    canvas = image.copy()
    height, width = canvas.shape[:2]
    scale = max(0.55, min(width, height) / 600.0)
    thickness = max(2, int(round(min(width, height) / 220)))
    for index, item in enumerate(objects, start=1):
        x, y, box_width, box_height = item["box"]
        cv2.rectangle(canvas, (x, y), (x + box_width, y + box_height), (0, 0, 255), thickness)
        text = str(index)
        text_size, baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
        top = max(0, y - text_size[1] - baseline - 7)
        right = min(width, x + text_size[0] + 9)
        cv2.rectangle(canvas, (x, top), (right, y), (0, 0, 255), -1)
        cv2.putText(
            canvas,
            text,
            (x + 4, max(text_size[1] + 1, y - baseline - 3)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

    if verdict == "defect" and predicted_class:
        banner = f"{predicted_class} | {confidence * 100:.1f}% | {len(objects)} regions"
        color = (0, 0, 220)
    else:
        banner = "OUT OF 6 CLASSES | REVIEW REQUIRED"
        color = (0, 140, 220)
    banner_width = width
    banner_height = max(28, int(round(min(width, height) * 0.08)))
    cv2.rectangle(canvas, (0, 0), (banner_width, banner_height), color, -1)
    base_scale = 0.55
    text_width = cv2.getTextSize(
        banner, cv2.FONT_HERSHEY_SIMPLEX, base_scale, 1
    )[0][0]
    font_scale = min(base_scale, max(0.32, (width - 20) / max(text_width, 1) * base_scale))
    cv2.putText(
        canvas,
        banner,
        (8, max(18, int(banner_height * 0.68))),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (255, 255, 255),
        max(1, thickness - 1),
        cv2.LINE_AA,
    )
    return canvas
