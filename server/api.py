"""FastAPI app wiring Copilot onto the OpenAI Chat Completions API."""

import threading
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

from copilot import CopilotClient
from copilot.auth import read_cached_auth
from copilot.capabilities import (
    available_models,
    discovery_complete,
    model_payload,
    resolve_model,
    save_discovered_models,
)
from copilot.driver import ClearanceRequired

from .config import MODEL_NAME, RATE_LIMIT_BURST, RATE_LIMIT_RPM
from .openai_format import (
    completion_response,
    new_id,
    sse_event,
    stream_chunk,
)
from .prompt import messages_to_prompt
from .ratelimit import TokenBucket
from .schemas import ChatCompletionRequest, ModelDiscoveryRequest

app = FastAPI(title="Copilot OpenAI-compatible API", version="1.0.0")
# Server must never pop a visible browser mid-request: chat and token refresh
# are plain HTTP, and if the session is gone entirely the request fails with a
# message to run `python -m copilot login` out of band.
client = CopilotClient(interactive_clear=False)

_CLEARANCE_HELP = (
    "Copilot asked for human verification before answering. Open copilot.com in "
    "your browser, pass the check, then retry (or run `python -m copilot login`)."
)

# Self-imposed rate limit on top of the concurrency lock below: this caps
# requests-per-minute, the lock caps requests-in-flight. See server/ratelimit.py.
_rate_limiter = TokenBucket(RATE_LIMIT_RPM, RATE_LIMIT_BURST)


def _rate_limited_response():
    """Spend a token; return an OpenAI-shaped 429 if none left, else ``None``."""
    allowed, wait = _rate_limiter.try_acquire()
    if allowed:
        return None
    secs = max(1, round(wait))
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(secs)},
        content={"error": {
            "message": (
                f"Rate limit exceeded (>{RATE_LIMIT_RPM:g} req/min). "
                f"Retry in {secs}s."
            ),
            "type": "rate_limit_error",
            "code": "rate_limit_exceeded",
        }},
    )

# Copilot's per-account chat socket doesn't tolerate concurrent conversations
# from one process (parallel requests error out or hang). This server bridges a
# single signed-in account, so we serialize upstream calls: concurrent HTTP
# requests queue here and run one at a time. Predictable, at the cost of
# parallelism — fine for a personal bridge.
_upstream_lock = threading.Lock()


def _stream(prompt: str, model: str, conversation_id=None):
    """Yield OpenAI ``chat.completion.chunk`` SSE events for ``prompt``.

    ``conversation_id`` continues an existing Copilot thread; ``None`` starts a
    fresh one (its id is emitted on the final chunk).
    """
    cid = new_id()
    created = int(time.time())
    try:
        with _upstream_lock:  # one upstream chat at a time (released on disconnect)
            yield sse_event(stream_chunk(cid, created, model, {"role": "assistant"}))
            stream = client.stream(prompt, conversation_id=conversation_id, model=model)
            for piece in stream:
                if isinstance(piece, str) and piece:
                    yield sse_event(stream_chunk(cid, created, model, {"content": piece}))
            # Copilot's conversation id is known once the stream has run; emit it
            # on the final chunk so callers can track the upstream thread.
            yield sse_event(
                stream_chunk(
                    cid, created, model, {}, finish="stop",
                    conversation_id=stream.conversation_id,
                )
            )
    except ClearanceRequired:
        yield sse_event(
            stream_chunk(cid, created, model, {"content": f"\n[error: {_CLEARANCE_HELP}]"}, finish="error")
        )
    except Exception as exc:  # surface errors to the client instead of hanging
        yield sse_event(
            stream_chunk(cid, created, model, {"content": f"\n[error: {exc}]"}, finish="error")
        )
    yield "data: [DONE]\n\n"


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": spec.id,
                "object": "model",
                "created": 0,
                "owned_by": "microsoft",
                "name": spec.label,
            }
            for spec in available_models()
        ],
    }


def _account_capabilities():
    auth = read_cached_auth()
    tenant = auth.get("tenant")
    account_type = "unknown"
    if tenant:
        account_type = (
            "consumer"
            if tenant == "84df9e7f-e9f6-40af-b435-aaaaaaaaaaaa"
            else "organization"
        )
    return {
        "authenticated": bool(auth.get("access_token") and auth.get("oid")),
        "account_type": account_type,
        "tenant": tenant,
        "license_type": auth.get("license_type"),
        "scenario": auth.get("scenario"),
        "agent_host": auth.get("agent_host"),
        "discovery_complete": discovery_complete(),
        "models": [model_payload(spec) for spec in available_models()],
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "copilot-eve", **_account_capabilities()}


@app.get("/v1/capabilities")
def capabilities():
    return _account_capabilities()


@app.post("/v1/capabilities/models")
def update_models(req: ModelDiscoveryRequest):
    try:
        save_discovered_models(req.models)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": str(exc), "type": "invalid_model_discovery"}},
        )
    return _account_capabilities()


@app.post("/v1/chat/completions")
def chat_completions(req: ChatCompletionRequest):
    prompt = messages_to_prompt(req.messages)
    if not prompt.strip():
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "no text content in messages", "type": "invalid_request_error"}},
        )
    model = req.model or MODEL_NAME
    try:
        resolve_model(model)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": str(exc), "type": "invalid_model"}},
        )

    # Enforce the per-minute ceiling before touching the upstream lock, so excess
    # callers get a fast 429 instead of piling up behind the serialized queue.
    limited = _rate_limited_response()
    if limited is not None:
        return limited

    if req.stream:
        return StreamingResponse(
            _stream(prompt, model, req.conversation_id), media_type="text/event-stream"
        )

    try:
        with _upstream_lock:  # serialize: one upstream chat at a time
            reply = client.chat(prompt, conversation_id=req.conversation_id, model=model)
    except ClearanceRequired:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": _CLEARANCE_HELP, "type": "clearance_required"}},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": {"message": str(exc), "type": "upstream_error"}},
        )
    return completion_response(reply.text, model, reply.conversation_id)


@app.get("/")
def root():
    return {
        "service": "Copilot OpenAI-compatible API",
        "endpoints": [
            "/health",
            "/v1/capabilities",
            "/v1/capabilities/models",
            "/v1/models",
            "/v1/chat/completions",
        ],
    }
