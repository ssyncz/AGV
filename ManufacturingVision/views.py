"""ManufacturingVision REST 接口（任务 4 裂纹检测 / 任务 5 工件识别）。"""
from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path

from django.core.files.base import ContentFile
from django.db.models import Avg, Count
from django.http import FileResponse
from rest_framework import mixins, status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from . import datasets
from . import services_detector
from . import services_supervised
from .models import VisionRecord
from .serializers import VisionRecordSerializer
from .services import (
    SHAPE_LABELS_ZH,
    analyze_crack,
    analyze_workpiece,
    annotate_crack,
    annotate_workpiece,
    decode_image,
    encode_image,
    load_image,
)


def _resolve_input(request):
    """从 multipart 上传或内置数据集样例解析输入，返回 (图像, 来源, 名称)。"""
    upload = request.FILES.get("image")
    if upload is not None:
        image = decode_image(upload.read())
        if image is None:
            raise ValueError("无法解析上传的图片，请确认格式为 jpg/png。")
        return image, VisionRecord.Source.UPLOAD, Path(upload.name).name

    sample = request.data.get("sample")
    if sample:
        path = datasets.resolve_sample_code(str(sample))
        image = load_image(path)
        if image is None:
            raise ValueError(f"数据集样例无法读取：{sample}")
        return image, VisionRecord.Source.DATASET, str(sample)

    raise ValueError("请上传图片（multipart 字段 image）或指定内置样例（字段 sample）。")


def _resolve_params(request) -> dict:
    raw = request.data.get("params")
    if raw in (None, "", "null"):
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("params 必须是 JSON 对象。")
    if not isinstance(parsed, dict):
        raise ValueError("params 必须是 JSON 对象。")
    return parsed


def _resolve_work_order(request):
    raw = request.data.get("work_order_id")
    if raw in (None, "", "null"):
        return None
    from Operations.models import WorkOrder

    try:
        return WorkOrder.objects.get(pk=int(raw))
    except (TypeError, ValueError, WorkOrder.DoesNotExist) as exc:
        raise ValueError("关联工单不存在。") from exc


def _resolve_quality_result(request, *, fallback: str) -> str:
    value = str(request.data.get("quality_result") or fallback).strip().lower()
    if value not in {"pass", "fail", "not_assessed"}:
        raise ValueError("quality_result 必须是 pass、fail 或 not_assessed。")
    return value


def _apply_quality_link(request, record, quality_result):
    if record.work_order_id and quality_result in {"pass", "fail"}:
        from Operations.services import (
            actor_from_request,
            record_quality_result,
            trace_id_from_request,
        )

        record_quality_result(
            record.work_order_id,
            record,
            quality_result,
            reason=str(request.data.get("quality_note") or ""),
            actor=actor_from_request(request),
            trace_id=trace_id_from_request(request),
        )


def _save_record(
    task_type, source, input_name, image, annotated, analysis, objects,
    *, work_order=None, quality_result="not_assessed",
):
    record = VisionRecord(
        task_type=task_type,
        work_order=work_order,
        quality_result=quality_result,
        source=source,
        input_name=input_name,
        verdict=analysis.get("result", task_type),
        object_count=analysis.get("count", 0),
        elapsed_ms=analysis.get("elapsed_ms", 0),
        detected_objects=objects,
        parameters=analysis.get("params", {}),
        metrics={
            "width": analysis.get("width"),
            "height": analysis.get("height"),
            "class_counts": analysis.get("class_counts", {}),
            "algorithm": analysis.get("algorithm", "opencv"),
            "fallback": bool(analysis.get("fallback", False)),
        },
    )
    stem = f"{task_type}_{uuid.uuid4().hex[:10]}"
    record.input_image.save(f"{stem}_input.jpg", ContentFile(encode_image(image)), save=False)
    record.result_image.save(f"{stem}_result.jpg", ContentFile(encode_image(annotated)), save=False)
    record.save()
    return record


class CrackDetectView(APIView):
    """POST /api/vision/crack/ 裂纹检测。"""

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        try:
            image, source, input_name = _resolve_input(request)
            params = _resolve_params(request)
            work_order = _resolve_work_order(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        # 默认用 Frangi：官方 DeepCrack 权重在 MT 磁瓦域泛化较差（实测 F1 0.56 vs 0.82），
        # 域内微调权重放好后，前端可显式切换到 deepcrack。
        algorithm = str(params.get("algorithm", "frangi")).strip().lower()
        use_deepcrack = algorithm in {"deepcrack", "supervised", "dl"}
        fallback = False
        if use_deepcrack:
            try:
                analysis = services_supervised.analyze_crack_supervised(image, params)
                annotated = services_supervised.annotate_crack_supervised(image, analysis)
            except (RuntimeError, ImportError) as exc:
                analysis = analyze_crack(image, params)
                annotated = annotate_crack(image, analysis)
                analysis["fallback_reason"] = str(exc)
                fallback = True
        else:
            analysis = analyze_crack(image, params)
            annotated = annotate_crack(image, analysis)

        analysis["algorithm"] = "frangi" if fallback else ("deepcrack" if use_deepcrack else "frangi")
        analysis["fallback"] = fallback
        try:
            quality_result = _resolve_quality_result(
                request,
                fallback=(
                    "fail" if analysis["result"] == "crack" else "pass"
                ) if work_order else "not_assessed",
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record = _save_record(
            VisionRecord.TaskType.CRACK, source, input_name, image, annotated, analysis,
            [{"box": box} for box in analysis["boxes"]],
            work_order=work_order,
            quality_result=quality_result,
        )
        _apply_quality_link(request, record, quality_result)
        return Response({
            "success": True,
            "task_type": "crack",
            "algorithm": analysis["algorithm"],
            "fallback": analysis["fallback"],
            "result": analysis["result"],
            "count": analysis["count"],
            "localized": analysis["localized"],
            "score": analysis["score"],
            "max_response": analysis["max_response"],
            "strongest_component": analysis["strongest_component"],
            "coverage": analysis.get("coverage"),
            "max_prob": analysis.get("max_prob"),
            "mean_prob": analysis.get("mean_prob"),
            "boxes": analysis["boxes"],
            "image_url": record.result_image.url,
            "input_image_url": record.input_image.url,
            "record_id": record.id,
            "work_order_id": work_order.id if work_order else None,
            "work_order_no": work_order.order_no if work_order else "",
            "quality_result": quality_result,
            "elapsed_ms": analysis["elapsed_ms"],
            "params": analysis["params"],
            "width": analysis["width"],
            "height": analysis["height"],
        })


class WorkpieceDetectView(APIView):
    """POST /api/vision/detect/ 工件识别。"""

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        try:
            image, source, input_name = _resolve_input(request)
            params = _resolve_params(request)
            work_order = _resolve_work_order(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        analysis = analyze_workpiece(image, params)
        annotated = annotate_workpiece(image, analysis)
        try:
            quality_result = _resolve_quality_result(
                request, fallback="pass" if work_order else "not_assessed"
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record = _save_record(
            VisionRecord.TaskType.WORKPIECE, source, input_name, image, annotated, analysis,
            analysis["objects"],
            work_order=work_order,
            quality_result=quality_result,
        )
        _apply_quality_link(request, record, quality_result)
        return Response({
            "success": True,
            "task_type": "workpiece",
            "count": analysis["count"],
            "objects": analysis["objects"],
            "class_counts": analysis["class_counts"],
            "class_labels": SHAPE_LABELS_ZH,
            "image_url": record.result_image.url,
            "input_image_url": record.input_image.url,
            "record_id": record.id,
            "work_order_id": work_order.id if work_order else None,
            "work_order_no": work_order.order_no if work_order else "",
            "quality_result": quality_result,
            "elapsed_ms": analysis["elapsed_ms"],
            "params": analysis["params"],
            "width": analysis["width"],
            "height": analysis["height"],
        })


class DefectDetectView(APIView):
    """POST /api/vision/detect/defect/ 缺陷检测（定位 + 分类，一次出框和类别）。"""

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        try:
            image, source, input_name = _resolve_input(request)
            params = _resolve_params(request)
            work_order = _resolve_work_order(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            analysis = services_detector.detect_defects(image, params)
        except (RuntimeError, ImportError) as exc:
            return Response(
                {"detail": f"{type(exc).__name__}: {exc}", **services_detector.status()},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        annotated = services_detector.annotate_defects(image, analysis)
        analysis["result"] = analysis["objects"][0]["class"] if analysis["objects"] else "normal"
        analysis["algorithm"] = "yolo"
        try:
            quality_result = _resolve_quality_result(
                request,
                fallback=("fail" if analysis["objects"] else "pass") if work_order else "not_assessed",
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        record = _save_record(
            VisionRecord.TaskType.DEFECT, source, input_name, image, annotated, analysis,
            analysis["objects"],
            work_order=work_order,
            quality_result=quality_result,
        )
        _apply_quality_link(request, record, quality_result)
        return Response({
            "success": True,
            "task_type": "defect",
            "algorithm": "yolo",
            "localized": True,
            "count": analysis["count"],
            "objects": analysis["objects"],
            "class_counts": analysis["class_counts"],
            "class_labels": services_detector.CLASS_LABELS_ZH,
            "result": analysis["result"],
            "model": analysis["model"],
            "image_url": record.result_image.url,
            "input_image_url": record.input_image.url,
            "record_id": record.id,
            "work_order_id": work_order.id if work_order else None,
            "work_order_no": work_order.order_no if work_order else "",
            "quality_result": quality_result,
            "elapsed_ms": analysis["elapsed_ms"],
            "params": analysis["params"],
            "width": analysis["width"],
            "height": analysis["height"],
        })


class VisionSampleListView(APIView):
    """GET /api/vision/samples/ 内置数据集样例列表。"""

    def get(self, request):
        return Response({"samples": datasets.all_samples(), "summary": datasets.dataset_summary()})


class VisionSampleImageView(APIView):
    """GET /api/vision/samples/<分组>/<文件名>/ 返回内置数据集原图，供前端预览。"""

    def get(self, request, group, name):
        try:
            path = datasets.resolve_sample(group, name)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        return FileResponse(open(path, "rb"), content_type=content_type)


class VisionOverviewView(APIView):
    """GET /api/vision/overview/ 视觉检测统计概览。"""

    def get(self, request):
        total = VisionRecord.objects.count()
        by_type = {
            item["task_type"]: item["count"]
            for item in VisionRecord.objects.values("task_type").annotate(count=Count("id"))
        }
        crack_records = VisionRecord.objects.filter(task_type=VisionRecord.TaskType.CRACK)
        crack_total = crack_records.count()
        crack_hits = crack_records.filter(verdict="crack").count()
        average_elapsed = VisionRecord.objects.aggregate(value=Avg("elapsed_ms"))["value"] or 0
        return Response({
            "total": total,
            "task_counts": by_type,
            "crack_total": crack_total,
            "crack_hits": crack_hits,
            "crack_hit_rate": round(crack_hits / crack_total * 100, 2) if crack_total else 0,
            "average_elapsed_ms": round(average_elapsed, 2),
            "dataset_summary": datasets.dataset_summary(),
            "recent_records": VisionRecordSerializer(
                VisionRecord.objects.all()[:8], many=True
            ).data,
        })


class VisionRecordViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """GET/DELETE /api/vision/records/ 检测记录（只读列表 + 删除）。"""

    queryset = VisionRecord.objects.all()
    serializer_class = VisionRecordSerializer
    ordering_fields = ["created_at", "elapsed_ms", "object_count"]

    def get_queryset(self):
        # 项目未安装 django-filter，这里直接按查询参数过滤，避免依赖共享配置。
        queryset = VisionRecord.objects.select_related("work_order").all()
        for field in ("task_type", "source", "verdict"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset
