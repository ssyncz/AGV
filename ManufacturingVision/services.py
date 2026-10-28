"""OpenCV 视觉检测算法（课程任务 4 裂纹检测 / 任务 5 工件识别）。

全部为传统图像处理方法，不依赖深度学习：

* 裂纹检测：高斯去噪 → 多尺度 Frangi 黑脊（vesselness）响应突出“细且暗、
  两侧更亮”的线状结构 → 连通域 + 最小外接矩形长宽比筛掉块状纹理与工件边缘 →
  用“最大脊响应 + 最强细长连通域”的组合得分判定。参数在 MT_Crack(57) /
  MT_Free(100) 上标定，标定与留出集结果见 README。
* 工件识别：双边滤波 → Otsu 阈值（按前景占比自动判断极性）→ 开闭运算 →
  外轮廓 → 多边形逼近 → 顶点数 / 圆度 / 边长比分类。置信分为几何规则与
  ``cv2.matchShapes`` 相似度的启发式组合，**不是校准概率**。

模块不依赖 Django，可在命令行、管理命令、接口与测试中直接复用。
"""
from __future__ import annotations

import math
import time
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

VISION_DEFAULTS: dict[str, dict[str, object]] = {
    "crack": {
        "max_side": 1024,
        "pre_blur_kernel": 3,
        "pre_blur_sigma": 0.6,
        "vessel_sigmas": (1.0, 1.4, 2.0, 2.8),
        "vessel_beta": 0.6,
        "vessel_threshold": 0.55,
        "min_aspect": 2.5,
        "score_vessel_weight": 0.7,
        "score_component_weight": 0.4,
        "component_length_scale": 0.05,
        "score_threshold": 0.54,
        "border_margin_ratio": 0.015,
        "border_margin_min": 8,
        "mask_threshold_ratio": 0.575,
        "mask_close_kernel": 3,
        "mask_skeleton": False,
        "mask_min_aspect": 2.5,
        "mask_border_margin": 0,
        "mask_dilation": 3,
    },
    "workpiece": {
        "blur_diameter": 9,
        "blur_sigma_color": 75.0,
        "blur_sigma_space": 75.0,
        "min_area": 300.0,
        "approx_epsilon": 0.02,
        "morph_kernel": 5,
        "min_circularity": 0.85,
    },
}

SHAPE_LABELS = ("circle", "triangle", "square", "rectangle", "hexagon", "unknown")
SHAPE_LABELS_ZH = {
    "circle": "圆形",
    "triangle": "三角形",
    "square": "正方形",
    "rectangle": "矩形",
    "hexagon": "六边形",
    "unknown": "未识别",
}
SHAPE_COLORS = {
    "circle": (66, 133, 244),
    "triangle": (52, 168, 83),
    "square": (251, 140, 0),
    "rectangle": (213, 0, 249),
    "hexagon": (0, 172, 193),
    "unknown": (128, 128, 128),
}


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _coerce(value, reference):
    if isinstance(reference, bool):
        return str(value).strip().lower() not in {"0", "false", "no", ""}
    if isinstance(reference, (list, tuple)):
        if isinstance(value, str):
            value = [part for part in value.replace(";", ",").split(",") if part.strip()]
        return [float(item) for item in value]
    if isinstance(reference, int):
        return int(round(float(value)))
    return float(value)


def _merged(kind: str, overrides) -> dict:
    """合并默认参数与请求覆盖参数，只接受已知键并做类型/奇偶校验。"""
    params = dict(VISION_DEFAULTS[kind])
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if key not in params:
                continue
            try:
                params[key] = _coerce(value, params[key])
            except (TypeError, ValueError):
                continue
    if kind == "crack":
        params["max_side"] = max(128, params["max_side"])
        params["pre_blur_kernel"] = max(1, params["pre_blur_kernel"] | 1)
        params["pre_blur_sigma"] = max(0.0, params["pre_blur_sigma"])
        try:
            sigmas = sorted(
                {round(float(item), 3) for item in params["vessel_sigmas"] if float(item) > 0}
            )
        except (TypeError, ValueError):
            sigmas = []
        params["vessel_sigmas"] = sigmas[:6] or [1.4]
        params["vessel_beta"] = min(max(params["vessel_beta"], 0.1), 2.0)
        params["vessel_threshold"] = min(max(params["vessel_threshold"], 0.05), 0.95)
        params["min_aspect"] = max(1.2, params["min_aspect"])
        params["component_length_scale"] = max(0.005, params["component_length_scale"])
        params["score_threshold"] = min(max(params["score_threshold"], 0.05), 3.0)
        params["border_margin_ratio"] = min(max(params["border_margin_ratio"], 0.0), 0.1)
        params["border_margin_min"] = max(0, params["border_margin_min"])
        params["mask_threshold_ratio"] = min(max(params["mask_threshold_ratio"], 0.0), 1.0)
        params["mask_close_kernel"] = min(max(params["mask_close_kernel"] | 1, 1), 15)
        params["mask_min_aspect"] = min(max(params["mask_min_aspect"], 1.0), 10.0)
        params["mask_border_margin"] = max(0, params["mask_border_margin"])
        params["mask_dilation"] = min(max(params["mask_dilation"], 0), 8)
    else:
        params["blur_diameter"] = max(3, params["blur_diameter"] | 1)
        params["morph_kernel"] = max(1, params["morph_kernel"])
        params["min_area"] = max(1.0, params["min_area"])
        params["approx_epsilon"] = min(max(params["approx_epsilon"], 0.005), 0.1)
    return params


def _to_gray(image: np.ndarray) -> np.ndarray:
    if image is None:
        raise ValueError("图像为空。")
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _limit_side(gray: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    """仅在长边超过 max_side 时等比缩小，返回 (图像, 缩放比例)。"""
    height, width = gray.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return gray, 1.0
    scale = max_side / float(longest)
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return cv2.resize(gray, new_size, interpolation=cv2.INTER_AREA), scale


def decode_image(buffer: bytes) -> np.ndarray | None:
    """从字节流解码为 BGR 图像，失败返回 None。"""
    if not buffer:
        return None
    array = np.frombuffer(buffer, dtype=np.uint8)
    if array.size == 0:
        return None
    return cv2.imdecode(array, cv2.IMREAD_COLOR)


def load_image(path) -> np.ndarray | None:
    """读取图片，兼容 Windows 中文路径。"""
    try:
        buffer = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buffer.size == 0:
        return None
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def encode_image(image: np.ndarray, quality: int = 92) -> bytes:
    """编码为 JPEG 字节流。"""
    success, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not success:
        raise ValueError("结果图片编码失败。")
    return buffer.tobytes()


def save_image(path, image: np.ndarray) -> None:
    """写盘，兼容 Windows 中文路径。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    success, buffer = cv2.imencode(f".{target.suffix.lstrip('.') or 'jpg'}", image)
    if not success:
        raise ValueError(f"图片写入失败：{target}")
    buffer.tofile(str(target))


# --------------------------------------------------------------------------- #
# 任务 4：裂纹检测
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=8)
def _vesselness_kernels(sigmas: tuple) -> tuple:
    """按尺度生成高斯一阶/二阶导数核，供 Frangi 黑脊响应复用。"""
    kernels = []
    for sigma in sigmas:
        radius = max(1, int(round(3.0 * sigma)))
        offsets = np.arange(-radius, radius + 1, dtype=np.float32)
        envelope = np.exp(-(offsets ** 2) / (2.0 * sigma * sigma))
        gauss = envelope / envelope.sum()
        first = -offsets / (sigma * sigma) * envelope
        first = first / np.abs(first).sum()
        second = (offsets ** 2 / sigma ** 4 - 1.0 / (sigma * sigma)) * envelope
        second = second / np.abs(second).sum()
        kernels.append((gauss.astype(np.float32), first.astype(np.float32), second.astype(np.float32)))
    return tuple(kernels)


def _vesselness_map(gray: np.ndarray, sigmas, beta: float) -> np.ndarray:
    """Frangi 黑脊响应：仅保留“细、暗、两侧更亮”的线状结构，抑制块状纹理与阶跃边缘。"""
    image = gray.astype(np.float32) / 255.0
    response = np.zeros_like(image)
    for gauss, first, second in _vesselness_kernels(tuple(sigmas)):
        hxx = cv2.sepFilter2D(image, cv2.CV_32F, second, gauss)
        hyy = cv2.sepFilter2D(image, cv2.CV_32F, gauss, second)
        hxy = cv2.sepFilter2D(image, cv2.CV_32F, first, first)
        root = np.sqrt(np.maximum((hxx - hyy) ** 2 + 4.0 * hxy ** 2, 0.0))
        lambda1 = 0.5 * (hxx + hyy - root)
        lambda2 = 0.5 * (hxx + hyy + root)
        ratio = np.abs(lambda1) / np.maximum(np.abs(lambda2), 1e-9)
        magnitude = np.sqrt(lambda1 ** 2 + lambda2 ** 2)
        peak = float(magnitude.max())
        cutoff = 0.5 * peak if peak > 0 else 1e-9
        value = np.exp(-(ratio ** 2) / (2.0 * beta * beta)) * (
            1.0 - np.exp(-(magnitude ** 2) / (2.0 * cutoff * cutoff))
        )
        response = np.maximum(response, np.where(lambda2 > 0.0, value, 0.0).astype(np.float32))
    return response


def _skeletonize_binary(binary: np.ndarray) -> np.ndarray:
    """Zhang-Suen 细化为一像素宽中心线，避免额外依赖 scikit-image。"""
    image = (binary > 0).astype(np.uint8)
    while True:
        changed = False
        for first_pass in (True, False):
            padded = np.pad(image, 1)
            p2 = padded[:-2, 1:-1]
            p3 = padded[:-2, 2:]
            p4 = padded[1:-1, 2:]
            p5 = padded[2:, 2:]
            p6 = padded[2:, 1:-1]
            p7 = padded[2:, :-2]
            p8 = padded[1:-1, :-2]
            p9 = padded[:-2, :-2]
            neighbors = (p2, p3, p4, p5, p6, p7, p8, p9)
            neighbor_count = sum(neighbors)
            transitions = sum(
                (neighbors[index] == 0) & (neighbors[(index + 1) % 8] == 1)
                for index in range(8)
            )
            if first_pass:
                condition_a = (p2 * p4 * p6) == 0
                condition_b = (p4 * p6 * p8) == 0
            else:
                condition_a = (p2 * p4 * p8) == 0
                condition_b = (p2 * p6 * p8) == 0
            remove = (
                (image == 1)
                & (neighbor_count >= 2)
                & (neighbor_count <= 6)
                & (transitions == 1)
                & condition_a
                & condition_b
            )
            if remove.any():
                image[remove] = 0
                changed = True
        if not changed:
            return image


def _long_component_mask(
    binary: np.ndarray,
    min_aspect: float,
    border_margin: int,
) -> np.ndarray:
    """保留细长连通域；border_margin=0 时允许裂纹接触图像边缘。"""
    total, labels, stats, _ = cv2.connectedComponentsWithStats(
        (binary > 0).astype(np.uint8), 8
    )
    height, width = binary.shape[:2]
    mask = np.zeros_like(binary, dtype=np.uint8)
    for index in range(1, total):
        x, y, box_w, box_h, _area = stats[index]
        if border_margin > 0 and (
            x <= border_margin
            or y <= border_margin
            or x + box_w >= width - border_margin
            or y + box_h >= height - border_margin
        ):
            continue
        component = labels == index
        points = np.column_stack(np.nonzero(component))[:, ::-1].astype(np.int32)
        (_center, (rect_w, rect_h), _angle) = cv2.minAreaRect(points)
        if max(rect_w, rect_h) / max(min(rect_w, rect_h), 1.0) < min_aspect:
            continue
        mask[component] = 1
    return mask


def refine_crack_mask(
    response: np.ndarray,
    params=None,
) -> tuple[np.ndarray, list[list[int]]]:
    """闭运算 + 骨架化 + 宽度校准，返回细化后的二值掩码与框。

    相对阈值以单图最大脊响应为基准，降低固定阈值在不同光照和对比度下的偏差。
    设置 ``mask_threshold_ratio=0`` 可回退到固定 ``vessel_threshold``。
    """
    resolved = _merged("crack", params)
    response = np.asarray(response, dtype=np.float32)
    if response.size == 0:
        return np.zeros(response.shape, dtype=np.uint8), []

    ratio = float(resolved["mask_threshold_ratio"])
    threshold = (
        max(float(response.max()), 1e-9) * ratio
        if ratio > 0
        else float(resolved["vessel_threshold"])
    )
    binary = (response >= threshold).astype(np.uint8)

    close_size = int(resolved["mask_close_kernel"])
    if close_size > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    if bool(resolved["mask_skeleton"]):
        binary = _skeletonize_binary(binary)

    binary = _long_component_mask(
        binary,
        float(resolved["mask_min_aspect"]),
        int(resolved["mask_border_margin"]),
    )
    dilation = int(resolved["mask_dilation"])
    if dilation > 0:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * dilation + 1, 2 * dilation + 1)
        )
        binary = cv2.dilate(binary, kernel, iterations=1)

    total, _labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    boxes = [
        [
            int(stats[index, cv2.CC_STAT_LEFT]),
            int(stats[index, cv2.CC_STAT_TOP]),
            int(stats[index, cv2.CC_STAT_WIDTH]),
            int(stats[index, cv2.CC_STAT_HEIGHT]),
        ]
        for index in range(1, total)
    ]
    return binary, boxes


def analyze_crack(image: np.ndarray, params=None) -> dict:
    """多尺度黑脊响应 + 细长线筛选判定裂纹，返回框、掩码与判定结果。"""
    started = time.perf_counter()
    resolved = _merged("crack", params)
    gray = _to_gray(image)
    original_h, original_w = gray.shape[:2]
    small, scale = _limit_side(gray, resolved["max_side"])

    blur_kernel = int(resolved["pre_blur_kernel"])
    if blur_kernel > 1:
        small = cv2.GaussianBlur(
            small, (blur_kernel, blur_kernel), float(resolved["pre_blur_sigma"])
        )

    response = _vesselness_map(
        small, resolved["vessel_sigmas"], float(resolved["vessel_beta"])
    )
    height, width = response.shape[:2]
    short_side = min(height, width)
    margin = int(
        max(float(resolved["border_margin_min"]), round(short_side * float(resolved["border_margin_ratio"])))
    )
    threshold = float(resolved["vessel_threshold"])
    binary = (response >= threshold).astype(np.uint8) * 255

    total, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    mask = np.zeros_like(binary)
    boxes: list[list[int]] = []
    strongest = 0.0
    for index in range(1, total):
        x, y, box_w, box_h, _area = stats[index]
        if (
            x <= margin
            or y <= margin
            or x + box_w >= width - margin
            or y + box_h >= height - margin
        ):
            continue  # 与图像边界相连，视为工件边缘或光照过渡，而非内部裂纹
        component = labels == index
        points = np.column_stack(np.nonzero(component))[:, ::-1].astype(np.int32)
        (_center, (rect_w, rect_h), _angle) = cv2.minAreaRect(points)
        length = max(rect_w, rect_h)
        thickness = max(min(rect_w, rect_h), 1.0)
        if length / thickness < resolved["min_aspect"]:
            continue  # 块状结构，不是裂纹
        length_ratio = length / float(short_side)
        peak = float(response[component].max())
        strongest = max(
            strongest,
            peak * min(length_ratio / float(resolved["component_length_scale"]), 1.0),
        )
        mask[component] = 255
        boxes.append([int(x), int(y), int(box_w), int(box_h)])

    interior = response[margin:height - margin, margin:width - margin]
    max_response = float(interior.max()) if interior.size else 0.0
    score = float(resolved["score_vessel_weight"]) * max_response + float(
        resolved["score_component_weight"]
    ) * strongest
    is_crack = score >= float(resolved["score_threshold"])

    if not is_crack:
        boxes = []
        mask[:] = 0
    else:
        mask, boxes = refine_crack_mask(response, resolved)
        mask = mask.astype(np.uint8) * 255
        if scale != 1.0:
            mask = cv2.resize(mask, (original_w, original_h), interpolation=cv2.INTER_NEAREST)
            boxes = [
                [
                    int(round(x / scale)),
                    int(round(y / scale)),
                    int(round(box_w / scale)),
                    int(round(box_h / scale)),
                ]
                for x, y, box_w, box_h in boxes
            ]

    elapsed = (time.perf_counter() - started) * 1000.0
    return {
        "task_type": "crack",
        "result": "crack" if is_crack else "normal",
        "count": len(boxes),
        "localized": bool(boxes),
        "boxes": boxes,
        "mask": mask,
        "score": round(score, 4),
        "max_response": round(max_response, 4),
        "strongest_component": round(strongest, 4),
        "width": original_w,
        "height": original_h,
        "params": resolved,
        "elapsed_ms": round(elapsed, 2),
    }


def annotate_crack(image: np.ndarray, analysis: dict) -> np.ndarray:
    """在结果图上绘制裂纹框与判定文字。"""
    canvas = image.copy()
    for x, y, width, height in analysis["boxes"]:
        cv2.rectangle(canvas, (x, y), (x + width, y + height), (0, 0, 255), 2)
    hit = analysis["result"] == "crack"
    score = analysis.get("score", 0)
    if hit and analysis.get("localized"):
        text = f"Crack x{analysis['count']} score={score:.2f}"
    elif hit:
        text = f"Crack (flag) score={score:.2f}"
    else:
        text = f"Normal score={score:.2f}"
    color = (0, 0, 255) if hit else (46, 160, 67)
    cv2.rectangle(canvas, (0, 0), (min(canvas.shape[1], 240), 28), color, -1)
    cv2.putText(
        canvas, text, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA
    )
    return canvas


# --------------------------------------------------------------------------- #
# 任务 5：工件识别
# --------------------------------------------------------------------------- #
def _side_lengths(approx: np.ndarray) -> list[float]:
    points = approx.reshape(-1, 2).astype(np.float64)
    if len(points) < 2:
        return [1.0]
    lengths = []
    for index in range(len(points)):
        nxt = points[(index + 1) % len(points)]
        lengths.append(float(np.linalg.norm(nxt - points[index])))
    return lengths


def _classify_shape(vertices: int, approx: np.ndarray, circularity: float, min_circularity: float) -> str:
    if circularity >= min_circularity and vertices >= 8:
        return "circle"
    if vertices == 3:
        return "triangle"
    if vertices == 4:
        sides = _side_lengths(approx)
        ratio = max(sides) / max(min(sides), 1e-6)
        return "rectangle" if ratio >= 1.3 else "square"
    if 5 <= vertices <= 7:
        return "hexagon"
    return "unknown"


@lru_cache(maxsize=1)
def _shape_templates() -> dict[str, np.ndarray]:
    """生成理想形状轮廓，用于 matchShapes 相似度打分。"""
    size, radius = 256, 100
    canvas = np.zeros((size, size), np.uint8)
    center = (size // 2, size // 2)

    def regular(sides: int) -> np.ndarray:
        points = []
        for index in range(sides):
            theta = -math.pi / 2 + index * 2 * math.pi / sides
            points.append([center[0] + radius * math.cos(theta), center[1] + radius * math.sin(theta)])
        return cv2.convexHull(np.array(points, np.float32).astype(np.int32))

    def outline(mask: np.ndarray) -> np.ndarray:
        found, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return max(found, key=cv2.contourArea)

    templates: dict[str, np.ndarray] = {}
    circle = canvas.copy()
    cv2.circle(circle, center, radius, 255, -1)
    templates["circle"] = outline(circle)
    for label, sides in (("triangle", 3), ("square", 4), ("hexagon", 6)):
        mask = canvas.copy()
        cv2.fillPoly(mask, [regular(sides)], 255)
        templates[label] = outline(mask)
    rectangle = canvas.copy()
    cv2.rectangle(
        rectangle,
        (center[0] - 100, center[1] - math.floor(100 / 1.8)),
        (center[0] + 100, center[1] + math.floor(100 / 1.8)),
        255,
        -1,
    )
    templates["rectangle"] = outline(rectangle)
    return templates


def _shape_similarity(contour: np.ndarray, template: np.ndarray | None) -> float:
    if template is None:
        return 0.5
    try:
        distance = cv2.matchShapes(contour, template, cv2.CONTOURS_MATCH_I1, 0.0)
    except cv2.error:
        return 0.5
    return float(1.0 / (1.0 + 10.0 * max(distance, 0.0)))


def _confidence(label: str, vertices: int, circularity: float, similarity: float) -> float:
    if label == "circle":
        geometry = min(max(circularity, 0.0), 1.0)
    elif label in {"triangle", "square", "rectangle", "hexagon"}:
        expected = {"triangle": 3, "square": 4, "rectangle": 4, "hexagon": 6}[label]
        geometry = max(0.0, 1.0 - abs(vertices - expected) / float(max(expected, 1)))
    else:
        geometry = 0.4
    score = 0.5 * geometry + 0.5 * similarity
    return round(min(max(score, 0.0), 1.0), 3)


def analyze_workpiece(image: np.ndarray, params=None) -> dict:
    """对单张图片做工件识别，返回目标列表与类别统计。"""
    started = time.perf_counter()
    resolved = _merged("workpiece", params)
    gray = _to_gray(image)
    original_h, original_w = gray.shape[:2]

    filtered = cv2.bilateralFilter(
        gray,
        int(resolved["blur_diameter"]),
        float(resolved["blur_sigma_color"]),
        float(resolved["blur_sigma_space"]),
    )
    _, binary = cv2.threshold(
        filtered, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
    )
    if float(np.count_nonzero(binary)) / float(binary.size) > 0.5:
        binary = cv2.bitwise_not(binary)
    kernel_size = int(resolved["morph_kernel"])
    structuring = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
    )
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, structuring)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, structuring)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    templates = _shape_templates()
    objects: list[dict] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < resolved["min_area"]:
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue
        approx = cv2.approxPolyDP(
            contour, float(resolved["approx_epsilon"]) * perimeter, True
        )
        vertices = len(approx)
        circularity = 4.0 * math.pi * area / (perimeter ** 2)
        label = _classify_shape(
            vertices, approx, circularity, float(resolved["min_circularity"])
        )
        similarity = _shape_similarity(contour, templates.get(label))
        x, y, width, height = cv2.boundingRect(contour)
        moments = cv2.moments(contour)
        if moments["m00"]:
            center_x = int(round(moments["m10"] / moments["m00"]))
            center_y = int(round(moments["m01"] / moments["m00"]))
        else:
            center_x, center_y = x + width // 2, y + height // 2
        objects.append(
            {
                "label": label,
                "box": [int(x), int(y), int(width), int(height)],
                "center": [center_x, center_y],
                "area": round(float(area), 2),
                "vertices": int(vertices),
                "circularity": round(float(circularity), 3),
                "score": _confidence(label, vertices, circularity, similarity),
            }
        )

    objects.sort(key=lambda item: (item["box"][1], item["box"][0]))
    class_counts: dict[str, int] = {}
    for item in objects:
        class_counts[item["label"]] = class_counts.get(item["label"], 0) + 1

    elapsed = (time.perf_counter() - started) * 1000.0
    return {
        "task_type": "workpiece",
        "count": len(objects),
        "objects": objects,
        "class_counts": class_counts,
        "mask": binary,
        "width": original_w,
        "height": original_h,
        "params": resolved,
        "elapsed_ms": round(elapsed, 2),
    }


def annotate_workpiece(image: np.ndarray, analysis: dict) -> np.ndarray:
    """在结果图上绘制每个工件的轮廓、类别与置信分。"""
    canvas = image.copy()
    for item in analysis["objects"]:
        x, y, width, height = item["box"]
        color = SHAPE_COLORS.get(item["label"], SHAPE_COLORS["unknown"])
        cv2.rectangle(canvas, (x, y), (x + width, y + height), color, 2)
        text = f"{item['label']} {item['score']:.2f}"
        text_size, _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        top = max(0, y - text_size[1] - 8)
        cv2.rectangle(canvas, (x, top), (x + text_size[0] + 8, top + text_size[1] + 7), color, -1)
        cv2.putText(
            canvas, text, (x + 4, top + text_size[1] + 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA,
        )
    summary = f"objects: {analysis['count']}"
    cv2.rectangle(canvas, (0, 0), (min(canvas.shape[1], 240), 28), (33, 37, 41), -1)
    cv2.putText(
        canvas, summary, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA
    )
    return canvas
