import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated
from weakref import WeakValueDictionary

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import AfterValidator, BaseModel, StringConstraints

from . import database


def nonblank_id(value: str) -> str:
    if not value.strip():
        raise ValueError("session_id is blank")
    return value


SessionId = Annotated[str, StringConstraints(min_length=1, max_length=128), AfterValidator(nonblank_id)]


class ChatRequest(BaseModel):
    session_id: SessionId
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    system_prompt: str | None = None


def parse_failures(header):
    failures = {}
    if header is None:
        return failures
    for pair in header.split(","):
        key, _, status = pair.strip().partition("=")
        if key not in ("key_1", "key_2", "*") or status not in ("429", "500", "502", "503"):
            raise HTTPException(422, "invalid X-Simulate-Failure header")
        for key_id in (("key_1", "key_2") if key == "*" else (key,)):
            failures[key_id] = int(status)
    return failures


@asynccontextmanager
async def lifespan(app):
    from .gateway import complete, open_gateway

    app.state.db = database.initialize(os.environ["DATABASE_URL"])
    app.state.simulate = os.getenv("ENABLE_FAILURE_SIMULATION", "").lower() == "true"
    app.state.locks = WeakValueDictionary()
    with open_gateway() as (router, cache):
        app.state.router = router
        app.state.cache = cache
        app.state.complete = complete
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[v.strip() for v in os.getenv("ALLOWED_ORIGINS", "").split(",") if v.strip()],
    allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Simulate-Failure"],
)


@app.exception_handler(sqlite3.Error)
async def database_error(request, exc):
    return JSONResponse({"detail": "database unavailable"}, status_code=503)


@app.exception_handler(Exception)
async def internal_error(request, exc):
    return JSONResponse({"detail": "internal server error"}, status_code=500)


@app.get("/health")
def health(request: Request):
    state = request.app.state
    database.check_database(state.db)
    return {"status": "ok", "keys_configured": len(state.router.model_list),
            "cache_enabled": state.cache is not None}


@app.get("/sessions/{session_id:path}/messages")
def history(request: Request, session_id: SessionId):
    _, messages = database.load_session(request.app.state.db, session_id)
    if not messages:
        raise HTTPException(404, "session not found")
    return {"session_id": session_id, "messages": messages}


@app.post("/chat")
async def chat(request: Request, body: ChatRequest, x_simulate_failure: Annotated[str | None, Header()] = None):
    start = perf_counter()
    state = request.app.state
    failures = parse_failures(x_simulate_failure) if state.simulate else {}
    lock = state.locks.setdefault(body.session_id, asyncio.Lock())
    async with lock:
        prompt, previous = database.load_session(state.db, body.session_id)
        if body.system_prompt is not None:
            prompt = body.system_prompt
        messages = [{"role": "system", "content": prompt if prompt is not None else "You are a helpful assistant."}]
        messages.extend({"role": row["role"], "content": row["content"]} for row in previous)
        messages.append({"role": "user", "content": body.message})
        try:
            reply, metadata = await state.complete(state.router, state.cache, messages, failures)
        except Exception:
            raise HTTPException(503, "all providers unavailable") from None
        metadata["latency_ms"] = round((perf_counter() - start) * 1000)
        database.save_turn(state.db, body.session_id, body.system_prompt, body.message, reply, metadata)
    return {"session_id": body.session_id, "reply": reply, "metadata": metadata}
