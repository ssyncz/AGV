# -*- coding: utf-8 -*-
"""制造视觉 —— 算法增强接口（Anomalib PatchCore / MVTec 数据集）

路由（挂在 /api/vision/algo/ 下）::

    GET  status/    依赖可用性
    POST dataset/   把项目数据转成 MVTec-AD 布局
    POST patchcore/ PatchCore 推理（需先训练）
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid

MAX_UPLOAD_BYTES = 10 * 1024 * 1024          # 单张图片上限 10 MB
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_ROOT = os.path.join(PROJECT_ROOT, "datasets", "auto", "_incoming")

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import datasets
from .services_supervised import segment_crack, status as deepcrack_status
from .services_defect import classify_defect, status as defect_status
from .services_algo import (
    anomalib_available,
    build_dataset_from_project,
    collect_dataset_paths,
    predict_patchcore,
)

PARSERS = (JSONParser, MultiPartParser, FormParser)


def _safe_category(value) -> str:
    """类别名只允许字母数字下划线短横线，长度 ≤32。"""
    cat = str(value or "mt_crack").strip()
    if not SAFE_TOKEN.match(cat):
        raise ValueError("category 只能包含字母、数字、下划线或短横线，且不超过 32 个字符")
    return cat


def _safe_dst_root(value) -> str | None:
    """dst_root 必须是 datasets/auto 下的子路径，禁止绝对路径与 .. 穿越。"""
    if value in (None, ""):
        return None
    base = os.path.abspath(os.path.join(PROJECT_ROOT, "datasets", "auto"))
    candidate = os.path.abspath(os.path.join(base, str(value)))
    if candidate != base and not candidate.startswith(base + os.sep):
        raise ValueError("dst_root 必须位于 datasets/auto 目录之内")
    return candidate


def _save_upload(upload) -> str:
    """把上传图片写进本次请求独有的临时目录，返回文件路径（调用方负责清理）。"""
    size = getattr(upload, "size", None) or 0
    if size > MAX_UPLOAD_BYTES:
        raise ValueError(f"图片过大，上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    name = os.path.basename(getattr(upload, "name", "") or "upload.jpg")
    ext = os.path.splitext(name)[1].lower() or ".jpg"
    if ext not in ALLOWED_EXT:
        raise ValueError("仅支持 jpg / jpeg / png / bmp / webp / tif 图片")
    os.makedirs(UPLOAD_ROOT, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="req_", dir=UPLOAD_ROOT)
    path = os.path.join(tmp_dir, f"upload_{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as f:
        for chunk in upload.chunks():
            f.write(chunk)
    return path


def _cleanup(path: str | None) -> None:
    if not path:
        return
    shutil.rmtree(os.path.dirname(path), ignore_errors=True)


class AlgoStatusView(APIView):
    """GET /api/vision/algo/status/"""

    def get(self, request):
        paths = collect_dataset_paths()
        return Response({
            "anomalib": anomalib_available(),
            "deepcrack": deepcrack_status(),
            "defect": defect_status(),
            "dataset": {k: len(v) for k, v in paths.items()},
            "install": "pip install -e ./vendor/anomalib",
        })


class DatasetBuildView(APIView):
    """POST /api/vision/algo/dataset/  → 生成 MVTec-AD 布局"""

    parser_classes = PARSERS

    def post(self, request):
        try:
            info = build_dataset_from_project(
                dst_root=_safe_dst_root(request.data.get("dst_root")),
                category=_safe_category(request.data.get("category")),
            )
        except Exception as exc:                     # pragma: no cover
            return Response({"detail": f"{type(exc).__name__}: {exc}"},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(info)


class PatchcoreInferView(APIView):
    """POST /api/vision/algo/patchcore/   {file} 或 {images:[...]}"""

    parser_classes = PARSERS

    def post(self, request):
        if not anomalib_available():
            return Response({"detail": "anomalib 未安装，请先 pip install -e ./vendor/anomalib"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "请上传图片（字段名 file）"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            tmp_path = _save_upload(upload)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = predict_patchcore([tmp_path],
                                       model_dir=request.data.get("model_dir") or None)
        except Exception as exc:
            return Response({"detail": f"{type(exc).__name__}: {exc}"},
                            status=status.HTTP_400_BAD_REQUEST)
        finally:
            _cleanup(tmp_path)
        return Response({"results": result})


class DeepCrackSegmentView(APIView):
    """POST /api/vision/algo/deepcrack/   {file}  → 监督式裂纹分割"""

    parser_classes = PARSERS

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"detail": "请上传图片（字段名 file）"},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            tmp_path = _save_upload(upload)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = segment_crack(tmp_path,
                                   device=request.data.get("device") or "cpu",
                                   threshold=float(request.data.get("threshold") or 0.5))
            result.pop("mask_png_bytes", None)      # 二进制不进 JSON
        except RuntimeError as exc:
            return Response({"detail": str(exc), **deepcrack_status()},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:                    # noqa: BLE001
            return Response({"detail": f"{type(exc).__name__}: {exc}"},
                            status=status.HTTP_400_BAD_REQUEST)
        finally:
            _cleanup(tmp_path)
        return Response(result)


class DefectClassifyView(APIView):
    """GET/POST /api/vision/algo/defect/   NEU 6 类表面缺陷识别。

    POST 参数：image（multipart 文件）或 sample（内置样例编码），
    返回 predicted_class / predicted_label / confidence / top3。
    """

    parser_classes = PARSERS

    def get(self, request):
        return Response(defect_status())

    def post(self, request):
        import time

        from .views import _resolve_input

        try:
            image, source, name = _resolve_input(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        started = time.perf_counter()
        try:
            result = classify_defect(image, device=request.data.get("device") or "cpu")
        except RuntimeError as exc:
            return Response({"detail": str(exc), **defect_status()},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:  # noqa: BLE001
            return Response({"detail": f"{type(exc).__name__}: {exc}"},
                            status=status.HTTP_400_BAD_REQUEST)

        result.update({
            "task_type": "defect",
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
        })
        if str(source) == "dataset" and str(name).startswith("neu/"):
            truth = datasets.load_neu_labels().get(os.path.basename(str(name)))
            if truth:
                result.update({
                    "ground_truth_class": truth["class"],
                    "ground_truth_label": truth["label"],
                    "match": result.get("predicted_class") == truth["class"],
                })
        return Response(result)
