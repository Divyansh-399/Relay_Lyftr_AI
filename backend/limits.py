import asyncio
import time
from collections import deque

from starlette.responses import JSONResponse


class PublicApiLimits:
    """Single-worker limits. Count all chat attempts, including failed simulations."""

    def __init__(self, app, per_minute=60, concurrent=8, body_bytes=131072):
        self.app = app
        self.per_minute = per_minute
        self.concurrent = concurrent
        self.body_bytes = body_bytes
        self.starts = deque()
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def protected_send(event):
            if event["type"] == "http.response.start":
                event["headers"] = list(event["headers"]) + [
                    (b"cache-control", b"no-store"), (b"referrer-policy", b"no-referrer"),
                    (b"x-content-type-options", b"nosniff"),
                ]
            await send(event)

        if scope["method"] != "POST" or scope["path"] != "/chat":
            return await self.app(scope, receive, protected_send)
        now = time.monotonic()
        while self.starts and self.starts[0] <= now - 60:
            self.starts.popleft()
        if self.active >= self.concurrent or len(self.starts) >= self.per_minute:
            response = JSONResponse({"detail": "chat capacity reached, try again shortly"}, 429,
                                    headers={"Retry-After": "60"})
            return await response(scope, receive, protected_send)
        self.starts.append(now)
        self.active += 1
        try:
            body = bytearray()
            try:
                async with asyncio.timeout(15):
                    while True:
                        event = await receive()
                        if event["type"] == "http.disconnect":
                            return
                        chunk = event.get("body", b"")
                        if len(body) + len(chunk) > self.body_bytes:
                            response = JSONResponse({"detail": "request body exceeds size limit"}, 422)
                            return await response(scope, receive, protected_send)
                        body.extend(chunk)
                        if not event.get("more_body"):
                            break
            except TimeoutError:
                response = JSONResponse({"detail": "request body timed out"}, 408)
                return await response(scope, receive, protected_send)

            async def buffered_receive():
                nonlocal body
                if body is None:
                    return await receive()
                data, body = body, None
                return {"type": "http.request", "body": bytes(data), "more_body": False}

            return await self.app(scope, buffered_receive, protected_send)
        finally:
            self.active -= 1
