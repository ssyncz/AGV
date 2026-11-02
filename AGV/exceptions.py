"""项目级 DRF 异常处理，统一返回可读的 JSON 错误。"""

from rest_framework.views import exception_handler as drf_exception_handler


def api_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

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
