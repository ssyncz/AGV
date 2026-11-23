# -*- coding: utf-8 -*-
"""DRF 统一异常处理：让接口在任何情况下都返回 JSON，而不是 Django 的 HTML 错误页。"""
from __future__ import annotations

import logging

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


def api_exception_handler(exc, context):
    """先交给 DRF 处理已知异常；未捕获异常记录日志并返回结构化 500。"""
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("未处理的 API 异常", exc_info=exc)
        return Response(
            {"detail": "服务器内部错误，请查看后端日志。"},
            status=500,
        )

    data = response.data
    if isinstance(data, dict) and "detail" not in data:
        # 序列化器字段错误保留原始字段，同时补一个通用 detail，便于前端统一展示。
        messages = []
        for field, errors in data.items():
            if isinstance(errors, (list, tuple)):
                messages.append(f"{field}: {'；'.join(str(item) for item in errors)}")
            else:
                messages.append(f"{field}: {errors}")
        if messages:
            data["detail"] = "；".join(messages)
    return response
