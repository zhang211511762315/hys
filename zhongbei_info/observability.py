import json
import logging
import time
import uuid


logger = logging.getLogger(__name__)


def validated_request_id(value: str | None) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return str(uuid.uuid4())


def log_legacy_rag_runtime_created(request_id: str) -> None:
    logger.info(json.dumps({"event": "legacy_rag_runtime.created", "request_id": request_id}))


class CorrelationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = validated_request_id(request.headers.get("X-Request-ID"))
        started_at = time.monotonic()
        try:
            response = self.get_response(request)
        except Exception:
            self._log_completion(request, 500, started_at)
            raise

        response["X-Request-ID"] = request.request_id
        if response.streaming:
            self._wrap_stream(response, request, started_at)
        else:
            self._log_completion(request, response.status_code, started_at)
        return response

    def _wrap_stream(self, response, request, started_at: float) -> None:
        stream = response.streaming_content
        if response.is_async:
            async def wrapped_async_stream():
                try:
                    async for chunk in stream:
                        yield chunk
                finally:
                    self._log_completion(request, response.status_code, started_at)

            response.streaming_content = wrapped_async_stream()
            return

        def wrapped_stream():
            try:
                yield from stream
            finally:
                self._log_completion(request, response.status_code, started_at)

        response.streaming_content = wrapped_stream()

    @staticmethod
    def _log_completion(request, status: int, started_at: float) -> None:
        record = {
            "request_id": request.request_id,
            "run_id": getattr(request, "agent_run_id", None),
            "method": request.method,
            "path": request.path,
            "status": status,
            "duration_ms": max(0, int((time.monotonic() - started_at) * 1000)),
        }
        logger.info(json.dumps(record))
