"""Start the OpenAI-compatible Copilot server:

    python app.py            # serves http://127.0.0.1:8000 (set HOST / PORT to override)

To bind a custom host/port from the command line, point uvicorn at the ASGI app:

    uvicorn server.api:app --host 0.0.0.0 --port 8080
"""

import sys

from server import app

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--login":
        # This is an explicitly requested gateway authorization, independent
        # of the normal Copilot browser tab Eve opens for the user.
        from copilot.browser import BrowserCopilot

        signed_in = BrowserCopilot(headless=False).login()
        raise SystemExit(0 if signed_in.get("access_token") else 1)
    if len(sys.argv) > 1:
        print("Usage: CopilotEveGateway [--login]", file=sys.stderr)
        raise SystemExit(2)
    app()  # blocks while uvicorn runs; does not open login UI by default
