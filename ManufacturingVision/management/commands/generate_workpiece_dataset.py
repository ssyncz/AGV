"""生成合成几何工件数据集（课程任务 5）。

背景为带光照渐变与噪声的浅灰画布，前景为随机位置、大小、旋转角度的
圆形 / 三角形 / 正方形 / 矩形 / 六边形，另加入少量面积低于检测下限的
干扰斑点，用于验证面积过滤是否有效。每张图的真值写入 ``labels.json``。

用法::

    python manage.py generate_workpiece_dataset --count 120 --size 400 --seed 42
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand

SHAPES = ("circle", "triangle", "square", "rectangle", "hexagon")
DEFAULT_OUT = "datasets/vision/workpiece"


def _regular_polygon(sides: int, cx: float, cy: float, radius: float, angle: float) -> np.ndarray:
    points = []
    for index in range(sides):
        theta = math.radians(angle - 90.0 + index * 360.0 / sides)
        points.append([cx + radius * math.cos(theta), cy + radius * math.sin(theta)])
    return np.array(points, np.int32).reshape(-1, 1, 2)


def _shape_contour(shape: str, cx: float, cy: float, radius: float, angle: float, size: int, rng):
    """把单个形状画到临时掩码上，返回 (层, 外轮廓)，真值框与面积由轮廓推导。"""
    layer = np.zeros((size, size), np.uint8)
    if shape == "circle":
        cv2.circle(layer, (int(round(cx)), int(round(cy))), int(round(radius)), 255, -1)
    elif shape == "rectangle":
        width = radius * 2.0
        height = width / rng.uniform(1.6, 2.2)
        box = ((cx, cy), (width, height), angle)
        cv2.fillPoly(layer, [cv2.boxPoints(box).astype(np.int32).reshape(-1, 1, 2)], 255)
    else:
        sides = {"triangle": 3, "square": 4, "hexagon": 6}[shape]
        cv2.fillPoly(layer, [_regular_polygon(sides, cx, cy, radius, angle)], 255)
    contours, _ = cv2.findContours(layer, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return layer, max(contours, key=cv2.contourArea)


def _render_image(rng, size: int, min_shapes: int, max_shapes: int):
    base = rng.uniform(205.0, 232.0)
    canvas = np.full((size, size), base, np.float32)
    canvas += np.tile(np.linspace(-9.0, 9.0, size, dtype=np.float32), (size, 1))

    objects = []
    placed = []
    for _ in range(rng.randint(min_shapes, max_shapes)):
        shape = rng.choice(SHAPES)
        for _attempt in range(40):
            radius = rng.uniform(size * 0.08, size * 0.19)
            cx = rng.uniform(radius + 6, size - radius - 6)
            cy = rng.uniform(radius + 6, size - radius - 6)
            if all(math.hypot(cx - px, cy - py) > (radius + pr + 8) for px, py, pr in placed):
                break
        else:
            continue
        angle = rng.uniform(0.0, 360.0)
        layer, contour = _shape_contour(shape, cx, cy, radius, angle, size, rng)
        area = float(cv2.contourArea(contour))
        if area < 400:
            continue
        canvas[layer > 0] = rng.uniform(60.0, 165.0)
        placed.append((cx, cy, radius))
        x, y, width, height = cv2.boundingRect(contour)
        objects.append({
            "label": shape,
            "bbox": [int(x), int(y), int(width), int(height)],
            "center": [int(round(cx)), int(round(cy))],
            "area": round(area, 1),
        })

    for _ in range(rng.randint(0, 2)):
        radius = rng.uniform(4.0, 7.0)
        cx = rng.uniform(radius, size - radius)
        cy = rng.uniform(radius, size - radius)
        value = base + rng.choice([-1.0, 1.0]) * rng.uniform(35.0, 70.0)
        cv2.circle(canvas, (int(round(cx)), int(round(cy))), int(round(radius)), float(value), -1)

    noise = np.random.default_rng(rng.randint(0, 10 ** 6)).normal(0.0, 3.2, canvas.shape)
    canvas = np.clip(canvas + noise, 0, 255).astype(np.uint8)
    canvas = cv2.GaussianBlur(canvas, (3, 3), 0.6)
    objects.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return canvas, objects


class Command(BaseCommand):
    help = "生成合成几何工件数据集（图片 + labels.json）"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=120, help="生成图片数量")
        parser.add_argument("--size", type=int, default=400, help="图片边长（正方形）")
        parser.add_argument("--seed", type=int, default=42, help="随机种子，保证可复现")
        parser.add_argument("--min-shapes", type=int, default=1, help="每张图最少工件数")
        parser.add_argument("--max-shapes", type=int, default=4, help="每张图最多工件数")
        parser.add_argument("--out", default=DEFAULT_OUT, help="输出目录（相对项目根目录）")

    def handle(self, *args, **options):
        out_dir = Path(options["out"])
        if not out_dir.is_absolute():
            out_dir = Path(settings.BASE_DIR) / out_dir
        image_dir = out_dir / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        for stale in image_dir.glob("wp_*.png"):
            stale.unlink()

        count = options["count"]
        size = options["size"]
        seed = options["seed"]
        images = []
        total_objects = 0
        for index in range(count):
            rng = random.Random(seed + index)
            canvas, objects = _render_image(
                rng, size, options["min_shapes"], options["max_shapes"]
            )
            name = f"wp_{index + 1:04d}.png"
            cv2.imwrite(str(image_dir / name), canvas)
            images.append({"file": name, "width": size, "height": size, "objects": objects})
            total_objects += len(objects)

        payload = {
            "source": "synthetic geometric workpiece dataset (OpenCV generated)",
            "seed": seed,
            "size": size,
            "count": count,
            "images": images,
        }
        (out_dir / "labels.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.stdout.write(self.style.SUCCESS(
            f"已生成 {count} 张图片、{total_objects} 个工件目标 → {out_dir}"
        ))
