"""Rejects request bodies over a byte limit before they are written anywhere."""

from fastapi import HTTPException
from starlette.responses import HTMLResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def describe_size(n: int) -> str:
    for unit, size in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if n >= size:
            return f"{n / size:g} {unit}"
    return f"{n} bytes"


class BodySizeLimit:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.message = f"Too large: a request may be at most {describe_size(max_bytes)}."

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = dict(scope["headers"]).get(b"content-length")
        if content_length is not None and int(content_length) > self.max_bytes:
            await HTMLResponse(f"<p>{self.message}</p>", status_code=413)(scope, receive, send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(status_code=413, detail=self.message)
            return message

        await self.app(scope, limited_receive, send)
