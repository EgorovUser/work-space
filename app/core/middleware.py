from __future__ import annotations

import uuid

from app.core.context import request_id_var
from app.core.logging import log_scope, logger


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = ""
        for key, value in scope.get("headers") or []:
            if key == b"x-request-id":
                request_id = value.decode("latin-1")[:64]
                break
        if not request_id:
            request_id = uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        status = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            try:
                code = status["code"]
                method = scope.get("method", "")
                path = scope.get("path", "")
                with log_scope("http", "request"):
                    line = "{} {} -> {}"
                    if code >= 400 or method not in ("GET", "HEAD", "OPTIONS"):
                        logger.info(line, method, path, code)
                    else:
                        logger.debug(line, method, path, code)
            except Exception:
                pass
            request_id_var.reset(token)
