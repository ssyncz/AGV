"""视觉数据集访问层。

目录结构（相对项目根目录）::

    datasets/vision/
    ├─ mt/
    │  ├─ crack/images/*.jpg     # MT_Crack 有裂纹样本（57 张）
    │  ├─ crack/masks/*.png      # 二值真值掩码，非零像素即裂纹
    │  └─ free/images/*.jpg      # MT_Free 无缺陷负样本（抽样 100 张）
    └─ workpiece/
       ├─ images/*.png           # 合成几何工件（120 张）
       └─ labels.json            # 合成数据真值标注

接口、管理命令与测试统一通过本模块定位数据，避免各处硬编码路径。
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings

VISION_DATASET_ROOT = Path(settings.BASE_DIR) / "datasets" / "vision"

MT_ROOT = VISION_DATASET_ROOT / "mt"
CRACK_IMAGE_DIR = MT_ROOT / "crack" / "images"
CRACK_MASK_DIR = MT_ROOT / "crack" / "masks"
FREE_IMAGE_DIR = MT_ROOT / "free" / "images"

WORKPIECE_ROOT = VISION_DATASET_ROOT / "workpiece"
WORKPIECE_IMAGE_DIR = WORKPIECE_ROOT / "images"
WORKPIECE_LABEL_FILE = WORKPIECE_ROOT / "labels.json"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

CRACK = "crack"
FREE = "free"
WORKPIECE = "workpiece"
SAMPLE_GROUPS = (CRACK, FREE, WORKPIECE)

GROUP_DIRS = {
    CRACK: CRACK_IMAGE_DIR,
    FREE: FREE_IMAGE_DIR,
    WORKPIECE: WORKPIECE_IMAGE_DIR,
}


def list_samples(group: str) -> list[str]:
    """列出某个分组下的样例文件名（升序）。"""
    if group not in GROUP_DIRS:
        raise ValueError(f"未知的数据集分组：{group}")
    directory = GROUP_DIRS[group]
    if not directory.exists():
        return []
    return sorted(
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def all_samples() -> dict[str, list[str]]:
    """返回 `{"crack": [...], "free": [...], "workpiece": [...]}`。"""
    return {group: list_samples(group) for group in SAMPLE_GROUPS}


def split_sample(sample: str) -> tuple[str, str]:
    """把 ``"crack/exp1_num_249594.jpg"`` 拆成 ``("crack", "exp1_num_249594.jpg")``。"""
    if not isinstance(sample, str) or "/" not in sample:
        raise ValueError("样例格式应为「分组/文件名」，例如 crack/exp1_num_249594.jpg。")
    group, name = sample.split("/", 1)
    group = group.strip()
    if group not in GROUP_DIRS:
        raise ValueError(f"未知的数据集分组：{group}")
    return group, name.strip()


def resolve_sample(group: str, name: str) -> Path:
    """把分组 + 文件名解析为真实路径，并阻止目录穿越。"""
    if group not in GROUP_DIRS:
        raise ValueError(f"未知的数据集分组：{group}")
    safe_name = Path(name).name
    if not safe_name or safe_name != name.strip():
        raise ValueError("样例文件名不合法。")
    directory = GROUP_DIRS[group].resolve()
    path = (directory / safe_name).resolve()
    if directory != path.parent or not path.is_file():
        raise ValueError(f"数据集样例不存在：{group}/{safe_name}")
    return path


def resolve_sample_code(sample: str) -> Path:
    group, name = split_sample(sample)
    return resolve_sample(group, name)


def crack_mask_path(image_name: str) -> Path | None:
    """返回裂纹图片对应的真值掩码路径，缺失时返回 None。"""
    mask = CRACK_MASK_DIR / f"{Path(image_name).stem}.png"
    return mask if mask.is_file() else None


def load_workpiece_labels() -> dict[str, list[dict]]:
    """读取合成工件标注，返回 ``{文件名: [对象, ...]}``。"""
    if not WORKPIECE_LABEL_FILE.is_file():
        return {}
    payload = json.loads(WORKPIECE_LABEL_FILE.read_text(encoding="utf-8"))
    images = payload.get("images", []) if isinstance(payload, dict) else payload
    return {item["file"]: item.get("objects", []) for item in images}


def dataset_summary() -> dict[str, int]:
    """数据集规模概览，用于 README、报告与接口。"""
    return {
        CRACK: len(list_samples(CRACK)),
        FREE: len(list_samples(FREE)),
        WORKPIECE: len(list_samples(WORKPIECE)),
    }
