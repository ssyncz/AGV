"""在数据集上批量评估视觉算法，输出报告级指标（课程任务 4/5）。

用法::

    python manage.py evaluate_vision --task all --out ManufacturingVision/reports

产物：

* ``crack_metrics.json/.csv``：按图判定的准确率 / 精确率 / 召回率 / F1，以及裂纹
  图像的像素级定位指标（IoU、像素精确率、像素召回率、3 像素容差召回率）。
* ``workpiece_metrics.json/.csv``：IoU≥0.5 匹配下的检测 P/R/F1、逐类 P/R 与形状
  分类准确率。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand

from ManufacturingVision import datasets
from ManufacturingVision.services import analyze_crack, analyze_workpiece, load_image

CRACK_TARGET = {"accuracy": 0.85, "f1": 0.80}
WORKPIECE_TARGET = {"f1": 0.85, "classification_accuracy": 0.90}
IOU_MATCH = 0.5
TOLERANCE_PIXELS = 3
SHAPE_LABELS = ("circle", "triangle", "square", "rectangle", "hexagon", "unknown")


def _prf(true_positive: int, false_positive: int, false_negative: int):
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)


def _iou(prediction: np.ndarray, ground_truth: np.ndarray) -> float:
    union = np.logical_or(prediction, ground_truth).sum()
    if union == 0:
        return 1.0
    return float(np.logical_and(prediction, ground_truth).sum() / union)


def _load_mask(path) -> np.ndarray:
    buffer = np.fromfile(str(path), dtype=np.uint8)
    mask = cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)
    return mask > 0 if mask is not None else np.zeros((1, 1), bool)


def _write_csv(path: Path, rows, fieldnames) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class Command(BaseCommand):
    help = "批量评估裂纹检测与工件识别算法，输出 CSV / JSON 指标"

    def add_arguments(self, parser):
        parser.add_argument("--task", choices=["crack", "workpiece", "all"], default="all")
        parser.add_argument("--out", default="ManufacturingVision/reports", help="报告输出目录")

    def handle(self, *args, **options):
        out_dir = Path(options["out"])
        if not out_dir.is_absolute():
            out_dir = Path(settings.BASE_DIR) / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        task = options["task"]
        if task in ("crack", "all"):
            self._evaluate_crack(out_dir)
        if task in ("workpiece", "all"):
            self._evaluate_workpiece(out_dir)

    def _evaluate_crack(self, out_dir: Path) -> None:
        rows = []
        true_positive = false_positive = true_negative = false_negative = 0
        ious = []
        pixel_precisions = []
        pixel_recalls = []
        tolerance_recalls = []

        crack_names = datasets.list_samples(datasets.CRACK)
        for name in crack_names:
            image = load_image(datasets.resolve_sample(datasets.CRACK, name))
            analysis = analyze_crack(image)
            predicted = analysis["result"] == "crack"
            true_positive += int(predicted)
            false_negative += int(not predicted)

            mask_path = datasets.crack_mask_path(name)
            iou = pixel_precision = pixel_recall = tolerance_recall = ""
            if mask_path is not None:
                ground_truth = _load_mask(mask_path)
                predicted_mask = analysis["mask"] > 0
                overlap = float(np.logical_and(predicted_mask, ground_truth).sum())
                pixel_precision = (
                    round(overlap / float(predicted_mask.sum()), 4) if predicted_mask.any() else 0.0
                )
                pixel_recall = (
                    round(overlap / float(ground_truth.sum()), 4) if ground_truth.any() else 1.0
                )
                iou = round(_iou(predicted_mask, ground_truth), 4)
                dilated = cv2.dilate(
                    predicted_mask.astype(np.uint8),
                    np.ones((TOLERANCE_PIXELS, TOLERANCE_PIXELS), np.uint8),
                ) > 0
                tolerance_hit = float(np.logical_and(dilated, ground_truth).sum())
                tolerance_recall = (
                    round(tolerance_hit / float(ground_truth.sum()), 4)
                    if ground_truth.any() else 1.0
                )
                ious.append(iou)
                pixel_precisions.append(pixel_precision)
                pixel_recalls.append(pixel_recall)
                tolerance_recalls.append(tolerance_recall)
            rows.append({
                "file": name, "group": "crack", "ground_truth": "crack",
                "prediction": analysis["result"], "localized": analysis["localized"],
                "score": analysis["score"], "boxes": analysis["count"],
                "iou": iou, "pixel_precision": pixel_precision,
                "pixel_recall": pixel_recall, "recall_tol3": tolerance_recall,
                "elapsed_ms": analysis["elapsed_ms"],
            })

        free_names = datasets.list_samples(datasets.FREE)
        for name in free_names:
            image = load_image(datasets.resolve_sample(datasets.FREE, name))
            analysis = analyze_crack(image)
            predicted = analysis["result"] == "crack"
            false_positive += int(predicted)
            true_negative += int(not predicted)
            rows.append({
                "file": name, "group": "free", "ground_truth": "normal",
                "prediction": analysis["result"], "localized": analysis["localized"],
                "score": analysis["score"], "boxes": analysis["count"],
                "iou": "", "pixel_precision": "", "pixel_recall": "",
                "recall_tol3": "", "elapsed_ms": analysis["elapsed_ms"],
            })

        total = true_positive + true_negative + false_positive + false_negative
        precision, recall, f1 = _prf(true_positive, false_positive, false_negative)
        accuracy = round((true_positive + true_negative) / total, 4) if total else 0.0
        localized = sum(1 for row in rows if row["group"] == "crack" and row["localized"])
        metrics = {
            "task": "crack",
            "dataset": {"crack": len(crack_names), "free": len(free_names), "total": total},
            "confusion": {
                "true_positive": true_positive, "false_positive": false_positive,
                "true_negative": true_negative, "false_negative": false_negative,
            },
            "accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1,
            "localization": {
                "crack_images": len(crack_names),
                "localized_images": localized,
                "mean_iou": round(float(np.mean(ious)), 4) if ious else 0.0,
                "mean_pixel_precision": round(float(np.mean(pixel_precisions)), 4) if pixel_precisions else 0.0,
                "mean_pixel_recall": round(float(np.mean(pixel_recalls)), 4) if pixel_recalls else 0.0,
                "mean_recall_tol3": round(float(np.mean(tolerance_recalls)), 4) if tolerance_recalls else 0.0,
                "note": "定位指标在全部 MT_Crack 图像上统计；未判定或未定位的图像按 0 计入。",
            },
            "targets": CRACK_TARGET,
            "pass": accuracy >= CRACK_TARGET["accuracy"] and f1 >= CRACK_TARGET["f1"],
        }
        (out_dir / "crack_metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_csv(
            out_dir / "crack_metrics.csv", rows,
            ["file", "group", "ground_truth", "prediction", "localized", "score", "boxes",
             "iou", "pixel_precision", "pixel_recall", "recall_tol3", "elapsed_ms"],
        )
        localization = metrics["localization"]
        self.stdout.write(self.style.SUCCESS(
            f"[裂纹] 准确率={accuracy} 精确率={precision} 召回率={recall} F1={f1} "
            f"平均IoU={localization['mean_iou']} 召回@3px={localization['mean_recall_tol3']} "
            f"已定位={localization['localized_images']}/{localization['crack_images']} "
            f"{'达标' if metrics['pass'] else '未达标'}"
        ))

    def _evaluate_workpiece(self, out_dir: Path) -> None:
        labels = datasets.load_workpiece_labels()
        rows = []
        true_positive = false_positive = false_negative = 0
        matched_total = correct_total = 0
        per_class = {label: {"tp": 0, "fp": 0, "fn": 0} for label in SHAPE_LABELS}

        for name, objects in sorted(labels.items()):
            image_path = datasets.WORKPIECE_IMAGE_DIR / name
            if not image_path.is_file():
                continue
            analysis = analyze_workpiece(load_image(image_path))
            predictions = analysis["objects"]

            candidates = []
            for gt_index, ground_truth in enumerate(objects):
                gx, gy, gw, gh = ground_truth["bbox"]
                for pred_index, prediction in enumerate(predictions):
                    px, py, pw, ph = prediction["box"]
                    inter_x = max(0, min(gx + gw, px + pw) - max(gx, px))
                    inter_y = max(0, min(gy + gh, py + ph) - max(gy, py))
                    intersection = inter_x * inter_y
                    union = gw * gh + pw * ph - intersection
                    if union > 0:
                        candidates.append((intersection / union, gt_index, pred_index))
            candidates.sort(reverse=True)

            used_gt = set()
            used_pred = set()
            correct = 0
            for overlap, gt_index, pred_index in candidates:
                if overlap < IOU_MATCH or gt_index in used_gt or pred_index in used_pred:
                    continue
                used_gt.add(gt_index)
                used_pred.add(pred_index)
                true_positive += 1
                matched_total += 1
                if objects[gt_index]["label"] == predictions[pred_index]["label"]:
                    correct += 1
                    correct_total += 1
                    per_class[objects[gt_index]["label"]]["tp"] += 1
                else:
                    per_class[objects[gt_index]["label"]]["fn"] += 1
                    per_class[predictions[pred_index]["label"]]["fp"] += 1
            missed = len(objects) - len(used_gt)
            spurious = len(predictions) - len(used_pred)
            for index, ground_truth in enumerate(objects):
                if index not in used_gt:
                    per_class[ground_truth["label"]]["fn"] += 1
            for index, prediction in enumerate(predictions):
                if index not in used_pred:
                    per_class[prediction["label"]]["fp"] += 1
            false_negative += missed
            false_positive += spurious

            rows.append({
                "file": name, "gt_count": len(objects), "pred_count": len(predictions),
                "matched": len(used_gt), "correct_label": correct,
                "missed": missed, "spurious": spurious,
                "elapsed_ms": analysis["elapsed_ms"],
            })

        precision, recall, f1 = _prf(true_positive, false_positive, false_negative)
        classification_accuracy = round(correct_total / matched_total, 4) if matched_total else 0.0
        classes = {}
        for label, counts in per_class.items():
            class_precision, class_recall, class_f1 = _prf(counts["tp"], counts["fp"], counts["fn"])
            classes[label] = {
                "tp": counts["tp"], "fp": counts["fp"], "fn": counts["fn"],
                "precision": class_precision, "recall": class_recall, "f1": class_f1,
            }
        metrics = {
            "task": "workpiece",
            "dataset": {"images": len(rows)},
            "detection": {
                "true_positive": true_positive, "false_positive": false_positive,
                "false_negative": false_negative, "iou_threshold": IOU_MATCH,
                "precision": precision, "recall": recall, "f1": f1,
            },
            "classification": {
                "matched": matched_total, "correct": correct_total,
                "accuracy": classification_accuracy, "per_class": classes,
            },
            "targets": WORKPIECE_TARGET,
            "pass": f1 >= WORKPIECE_TARGET["f1"]
            and classification_accuracy >= WORKPIECE_TARGET["classification_accuracy"],
        }
        (out_dir / "workpiece_metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_csv(
            out_dir / "workpiece_metrics.csv", rows,
            ["file", "gt_count", "pred_count", "matched", "correct_label", "missed", "spurious", "elapsed_ms"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"[工件] 检测P={precision} R={recall} F1={f1} 分类准确率={classification_accuracy} "
            f"{'达标' if metrics['pass'] else '未达标'}"
        ))
