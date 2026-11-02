import uuid


class RequestIDMiddleware:
    """为每个 API 请求注入可追踪的 request_id。"""

    header_name = "HTTP_X_REQUEST_ID"
    response_header = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = (
            request.META.get(self.header_name) or uuid.uuid4().hex
        )[:64]
        response = self.get_response(request)
        response[self.response_header] = request.request_id
        return response
