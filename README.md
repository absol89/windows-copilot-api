# Windows Copilot API: a free LLM API powered by Microsoft Copilot

**Using your own Microsoft Copilot account.** No API key, no credits, no paid plan: it turns the free chat at [copilot.microsoft.com](https://copilot.microsoft.com) into an API you can call from code.

You can use it in two ways:

- 🐍 **As a Python library:** just call `client.chat("Hi")`. Supports streaming and multi-turn conversations.
- 🔌 **As a local OpenAI-compatible API:** runs a server at `http://localhost:8000/v1` that speaks the OpenAI format, so the official `openai` SDK (and any OpenAI-compatible app) works as a drop-in, with `localhost` in place of OpenAI.

You sign in once with your Microsoft account in a browser; your session is saved and refreshed automatically after that.

> **Unofficial project.** Not affiliated with or endorsed by Microsoft. It automates the consumer Copilot web experience for personal use, so use it responsibly and within Microsoft's terms.

---

## Why use this?

- **Free:** uses your normal signed-in Copilot, no API billing.
- **Drop-in OpenAI replacement:** point any OpenAI client at `localhost` and it just works.
- **Works everywhere you're signed in:** the signed-in path works even in regions where *anonymous* Copilot is blocked (e.g. India).
- **Streaming + conversations:** token-by-token output and multi-turn threads addressed by `conversation_id`.

---

## Requirements

- **Python 3.9+**
- A **Microsoft account** (the free one you use for Copilot is fine)
- Works on Windows, macOS, and Linux

---

## Setup (2 minutes)

### Native release bundle (recommended for ParadigmEve)

Release bundles contain the Python runtime dependencies and a Playwright Chromium fallback, so the
target computer does **not** need Git, a repository clone, Python, pip, or `playwright install`.
Download/extract the bundle for the target OS/architecture, then run:

```text
windows-copilot-api login --session-dir <writable app-owned folder>
windows-copilot-api serve --session-dir <same folder> --host 127.0.0.1 --port 8000
```

The portable default uses the bundled Chromium. A managed host such as ParadigmEve can instead ask
Playwright to use an installed branded browser, for example `--browser-channel msedge` or
`--browser-channel chrome`, while keeping the persistent profile in the explicitly supplied session
directory. The normal user machine never needs GitHub access; GitHub is only a build/release source.

A managed host may also pass `--profile-dir <exact directory>` to select the persistent Chromium
profile explicitly. This supports a product choice between an isolated Eve-owned Copilot profile and
an explicitly selected user profile. The bridge does not copy cookies, tokens, or profile state
between those directories. The bundled Playwright Chromium remains the portable default, so Copilot
does not depend on Edge, Chrome, or another browser already being installed.

Native CI builds cover Windows x64/ARM64, macOS Intel/Apple Silicon and Linux x64/ARM64.

For the `1.0.0` release, consumers can use stable release-asset URLs with these exact filenames:

- `windows-copilot-api-1.0.0-windows-x64.zip`
- `windows-copilot-api-1.0.0-windows-arm64.zip`
- `windows-copilot-api-1.0.0-macos-x64.tar.gz`
- `windows-copilot-api-1.0.0-macos-arm64.tar.gz`
- `windows-copilot-api-1.0.0-linux-x64.tar.gz`
- `windows-copilot-api-1.0.0-linux-arm64.tar.gz`
- `SHA256SUMS.txt`

The release tag intentionally has **no `v` prefix** (`1.0.0`) so downstream packagers can construct
the asset URL mechanically and pin the matching checksum.

```bash
# 1. Clone the project
git clone <your-repo-url>
cd Windows-Copilot-API
```

**2. Create and activate a virtual environment**

On **macOS / Linux**:

```bash
python3 -m venv venv
source venv/bin/activate
```

On **Windows** (PowerShell):

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

> On Windows you may need to allow script execution once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. In `cmd.exe` activate with `venv\Scripts\activate.bat` instead.

**3. Install dependencies and sign in**

```bash
# Install dependencies
pip install -r requirements.txt

# Install the browser Playwright needs (one-time)
playwright install chromium

# Sign in once: a browser opens, log into your Microsoft account
python -m copilot login
```

That's it. Your session is saved under `session/` (git-ignored, never shared) and reused on every run.

> 💡 You can even skip step 4: the **first** time you call `chat()` or start the server, it opens the sign-in browser for you automatically.

---

## Usage 1: In Python (no server)

The simplest way if your code is already Python.

```python
from copilot import CopilotClient

client = CopilotClient()                 # loads your signed-in session

# Get a full reply
reply = client.chat("Say hello in one short sentence.")
print(reply.text)

# Continue the SAME conversation — pass the id back
reply2 = client.chat("And now in French?", reply.conversation_id)
print(reply2.text)

# Stream the answer as it's typed
for chunk in client.stream("Tell me a short joke"):
    print(chunk, end="", flush=True)
```

`chat()` returns the full text plus a `conversation_id`; pass that id back to keep the thread going, or omit it to start fresh. `stream()` yields the reply piece by piece.

👉 More: [examples/01_direct_chat.py](examples/01_direct_chat.py), [02_direct_conversation.py](examples/02_direct_conversation.py), [03_direct_stream.py](examples/03_direct_stream.py)

---

## Usage 2: As an OpenAI-compatible server

Start a local server that speaks the OpenAI API, so existing OpenAI tools and SDKs work unchanged.

```bash
python app.py
# -> Copilot OpenAI-compatible API on http://127.0.0.1:8000
```

Then point any OpenAI client at it (the API key is required by the SDK but ignored):

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="unused")

resp = client.chat.completions.create(
    model="copilot",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)
```

Or call it with plain HTTP / `curl`:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'
```

**Endpoints**

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/v1/chat/completions` | Chat (supports `"stream": true` and an optional `"conversation_id"`) |
| `GET`  | `/v1/models` | Lists the single `copilot` model |

> Change the address with env vars: `HOST=0.0.0.0 PORT=8080 python app.py`, or run `uvicorn server.api:app --host 0.0.0.0 --port 8080`.

👉 More: [examples/04_server_http.py](examples/04_server_http.py), [05_server_stream.py](examples/05_server_stream.py), [06_server_openai_sdk.py](examples/06_server_openai_sdk.py)

---

## Command line

```bash
python -m copilot login          # sign in and save the session
python -m copilot ask "Hello!"   # quick one-shot question
```

---

## Concurrency & stress test

The server bridges a **single** signed-in Copilot account, and Copilot's chat
socket doesn't tolerate concurrent conversations from one process. So the server
**serializes** upstream calls: parallel HTTP requests queue behind a lock and run
one at a time (see [server/api.py](server/api.py)). This is intentional, and it
means throughput is sequential, not parallel.

You can measure where it breaks with the included stress test, which fires a
batch of simultaneous requests and **doubles the batch size every successful
round** until the first error:

```bash
# Start the server in one terminal
python app.py

# Ramp concurrency in another (1 → 2 → 4 → 8 → …)
python tests/stress.py
python tests/stress.py --max 64 --timeout 120 --url http://localhost:8000
```

**Sample run** (one signed-in account):

| Concurrency | Result | Wall time | Latency (min / median / max) |
| --- | --- | --- | --- |
| 1 | ✓ all ok | 3.7s | 3.7 / 3.7 / 3.7s |
| 2 | ✓ all ok | 4.6s | 3.4 / 4.6 / 4.6s |
| 4 | ✓ all ok | 8.3s | 3.7 / 6.7 / 8.3s |
| 8 | ✗ 1 failed (`HTTP 502`) | 13.3s | 3.5 / 9.7 / 13.3s |

**Highest fully-successful concurrency: 4.** Wall time roughly doubles each round
while *minimum* latency stays flat (~3.5s) — the signature of a serialized queue:
one request runs immediately, the rest wait their turn. The failure at 8 is an
upstream `502` (Copilot rejecting requests under load), not a server crash or
timeout — so the exact break point is flaky and may vary between runs.

> Takeaway: keep concurrent in-flight requests low (≈ 1–4). This is a personal
> bridge, not a high-throughput gateway — and please don't hammer your account.

---

## Project layout

| Path | What it does |
| --- | --- |
| [copilot/](copilot/) | The core library: `CopilotClient`, auth, browser sign-in, HTTP driver |
| [server/](server/) | The FastAPI OpenAI-compatible server |
| [examples/](examples/) | Runnable examples for every feature ([examples/README.md](examples/README.md)) |
| [tests/](tests/) | Test scripts, including the concurrency stress test ([tests/stress.py](tests/stress.py)) |
| [app.py](app.py) | Starts the server |

---

## Notes & limitations

- **Sign in once, then reuse.** The cached token refreshes automatically; you only re-sign-in if the session fully expires.
- **No daily limit, but be reasonable.** Microsoft doesn't impose a daily chat cap, but please use it in moderation, and don't spam or hammer it with automated bulk requests.
- **One model.** Copilot has no model picker, so the server advertises a single model named `copilot`.
- **Your session is private.** Everything in `session/` (cookies + token) stays on your machine and is git-ignored.

---

## License

For personal and educational use. You are responsible for complying with Microsoft's terms of service.
