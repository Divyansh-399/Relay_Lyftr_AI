import asyncio
import os
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from gateway import Gateway, Unavailable
from limits import PublicApiLimits
from storage import History


class JsonCors(CORSMiddleware):
    def preflight_response(self, request_headers):
        response = super().preflight_response(request_headers)
        if response.status_code < 400:
            return response
        headers = {k: v for k, v in response.headers.items()
                   if k not in {"content-type", "content-length"}}
        return JSONResponse({"detail": "CORS preflight denied"}, response.status_code, headers)


class Chat(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)
    system_prompt: str | None = Field(default=None, max_length=4000)

    @field_validator("session_id", "message", "system_prompt")
    @classmethod
    def valid_unicode(cls, value):
        if value is not None:
            value.encode("utf-8")
        return value

    @field_validator("message", mode="before")
    @classmethod
    def trim_message(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("session_id")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("session_id must contain text")
        return value


def parse_failures(header, enabled):
    if not enabled or not header:
        return {}
    failures = {}
    for item in header.split(","):
        match = re.fullmatch(r"(key_[1-9][0-9]*|\*)=(429|500|502|503)", item.strip())
        if not match:
            raise HTTPException(422, "invalid X-Simulate-Failure")
        failures[match[1]] = int(match[2])
    return failures


def create_app(gateway_factory=Gateway.configured):
    @asynccontextmanager
    async def lifespan(app):
        app.state.db = History(os.getenv("DATABASE_URL", "sqlite:///data/app.db"))
        app.state.gateway = gateway_factory()
        app.state.simulate = os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower() == "true"
        # Bounded lock table serializes same-session turns in this single-worker service.
        app.state.locks = [asyncio.Lock() for _ in range(256)]
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    app.add_middleware(PublicApiLimits,
                       per_minute=int(os.getenv("CHAT_REQUESTS_PER_MINUTE", "60")),
                       concurrent=int(os.getenv("CHAT_MAX_CONCURRENT", "8")))
    app.add_middleware(JsonCors, allow_origins=[o.strip() for o in origins],
                       allow_methods=["POST", "GET"], allow_headers=["Content-Type", "X-Simulate-Failure"])

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        return JSONResponse({"detail": "internal service error"}, status_code=500)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({"detail": "invalid request: check session_id, message and system_prompt"}, 422)

    @app.get("/health")
    async def health():
        with app.state.db.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok", "keys_configured": len(app.state.gateway.keys), "cache_enabled": True}

    @app.get("/sessions/{session_id}/messages")
    async def history(session_id: str):
        system, messages = app.state.db.read(session_id)
        if system is None:
            raise HTTPException(404, "session not found")
        return {"session_id": session_id, "messages": messages}

    @app.post("/chat")
    async def chat(body: Chat, x_simulate_failure: str | None = Header(default=None)):
        started = time.perf_counter()
        failures = parse_failures(x_simulate_failure, app.state.simulate)
        sid = body.session_id
        async with app.state.locks[hash(sid) % len(app.state.locks)]:
            system, history = app.state.db.read(sid)
            if body.system_prompt is not None:
                system = body.system_prompt
            if system is None:
                system = "You are a helpful, concise assistant."
            messages = [{"role": "system", "content": system}]
            messages.extend({"role": m["role"], "content": m["content"]} for m in history)
            messages.append({"role": "user", "content": body.message})
            if sum(len(m["content"]) for m in messages) > 64000:
                raise HTTPException(422, "session context is full, start a new session")
            try:
                reply, meta = await app.state.gateway.answer(messages, failures)
            except Unavailable:
                raise HTTPException(503, "all providers unavailable") from None
            meta["latency_ms"] = round((time.perf_counter() - started) * 1000)
            app.state.db.append(sid, system, body.message, reply, meta)
        return {"session_id": sid, "reply": reply, "metadata": meta}

    return app


app = create_app()

