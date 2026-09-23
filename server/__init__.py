"""OpenAI-compatible HTTP server for Microsoft Copilot.

Start it:

    from server import app
    app()

(`python app.py` in the project root does exactly this.) The server runs on
http://127.0.0.1:8000 — set HOST / PORT to override. It bridges the OpenAI Chat
Completions shape onto :class:`copilot.CopilotClient`; sign in once first with
``python -m copilot login``.

Code is split by concern:

    config.py         constants
    schemas.py        pydantic request models
    prompt.py         flatten OpenAI messages -> one Copilot prompt
    openai_format.py  build OpenAI response/chunk shapes
    api.py            FastAPI app, routes, upstream serialization
"""

import os

from .api import app as _api


def app(host="127.0.0.1", port=8000) -> None:
    """Start the server (blocks while uvicorn runs).

    The resident Microsoft 365 browser driver owns sign-in/session state. Packaged
    deployments should run `windows-copilot-api login` once before starting the server.
    """
    import uvicorn

    host = host or os.environ.get("HOST", "127.0.0.1")
    port = port or int(os.environ.get("PORT", "8000"))

    print(f"Copilot OpenAI-compatible API on http://{host}:{port}  (POST /v1/chat/completions)")
    uvicorn.run(_api, host=host, port=port)


__all__ = ["app"]
