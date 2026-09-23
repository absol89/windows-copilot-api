"""Resident browser that drives Microsoft 365 Copilot and reads its WebSocket.

Three ideas carry this file.

Playwright owns the browser but not the conversation. We type into the real
composer and press Enter, then read the reply off the Chathub WebSocket frames
the page already receives instead of scraping rendered HTML. The DOM can tell you
text stopped growing; the wire tells you the turn is *finished*, which is a
different and much more useful fact (`type: 3` closes the invocation).

Playwright's sync API objects belong to the thread that created them, so
everything browser-shaped runs on one dedicated worker thread and callers talk to
it over queues. That pattern comes from agentry's CopilotSDKBackend._call
(https://github.com/aweussom/agentry, backends.py:205), which does the same trick
to bridge an asyncio SDK onto a synchronous interface.

`tone` — the field carrying model choice — is **per conversation**. A new chat
resets to `Magic` no matter what was selected elsewhere. So changing model means
starting a fresh conversation and setting the picker before the first send, which
is why switch_tone() reloads the page.
"""

from __future__ import annotations

import base64
import json
import os
import queue
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterator

from playwright.sync_api import sync_playwright

def split_records(payload: str):
    return [part for part in payload.split("\x1e") if part.strip()]


def redact_url(url: str) -> str:
    return re.sub(r"([?&](?:access_token|accessToken)=)[^&]+", r"\1REDACTED", url, flags=re.I)

CHAT_URL = os.environ.get("COPILOT_CHAT_URL", "https://copilot.cloud.microsoft/chat")
CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{7,127}$")
CONVERSATION_PATH_RE = re.compile(r"/chat/conversation/([A-Za-z0-9][A-Za-z0-9-]{7,127})(?:[/?#]|$)")


def conversation_id_from_url(url: str) -> str | None:
    """Extract the durable Copilot conversation id from an M365 chat URL."""
    match = CONVERSATION_PATH_RE.search(url or "")
    return match.group(1) if match else None


def conversation_url(conversation_id: str) -> str:
    """Build the exact M365 Copilot URL for a validated conversation id."""
    if not CONVERSATION_ID_RE.fullmatch(conversation_id or ""):
        raise ValueError("invalid Copilot conversation id")
    return f"{CHAT_URL.rstrip('/')}/conversation/{conversation_id}"


def default_profile_dir() -> Path:
    """Return the persistent profile selected by the host/runtime.

    A managed host such as ParadigmEve may deliberately point at either its own
    isolated Copilot profile or an explicitly selected user profile.  An exact
    profile override wins over the app-owned session root; there is never any
    implicit copying between those profile identities.
    """
    explicit_profile = os.environ.get("COPILOT_PROFILE_DIR", "").strip()
    if explicit_profile:
        return Path(explicit_profile).expanduser().resolve()
    session_root = os.environ.get("COPILOT_SESSION_DIR", "").strip()
    if session_root:
        return Path(session_root).expanduser().resolve() / "profile-m365"
    return Path(__file__).parent / "session" / "profile-m365"


PROFILE_DIR = default_profile_dir()

# Discovered with probe_dom.py, not guessed. The composer is a <span> with
# role="textbox"; tag-qualified selectors miss it. Match on role and
# contenteditable, which do not change with UI language.
COMPOSER_SELECTORS = (
    '[role="textbox"][contenteditable="true"]',
    '[contenteditable="true"][aria-label*="Copilot"]',
    "textarea",
    '[contenteditable="true"]',
)

# The picker button's accessible name is localized ("Modellvelger" in Norwegian);
# its inner text is the current selection.
PICKER_SELECTORS = (
    '[aria-label*="odellvelger"]',
    '[aria-label*="odel"]',
    "button[aria-haspopup]",
)

# tone value -> the picker entry that selects it. Section 2 entries live behind a
# provider submenu that opens on hover.
TONES: dict[str, dict[str, str]] = {
    "Magic": {"label": "Auto", "title": "Auto", "owned_by": "microsoft"},
    "Chat": {"label": "Quick response", "title": "Quick response", "owned_by": "microsoft"},
    "Reasoning": {"label": "Think deeper", "title": "Think deeper", "owned_by": "microsoft"},
    "Gpt_5_6_Reasoning": {
        "label": "GPT 5.6 Think deeper",
        "title": "GPT 5.6 Think deeper",
        "owned_by": "openai",
    },
    # Was Gpt_5_5_Chat until 2026-09-15, when this tenant's
    # modelSelectorMetadata showed 5.5 replaced by 5.6. Old threads on 5.5 still
    # open; the menu just stopped offering it. The values outlive the buttons.
    "Gpt_5_6_Chat": {
        "label": "GPT 5.6 Quick response",
        "title": "GPT 5.6 Quick response",
        "owned_by": "openai",
    },
}
# What a *fresh Copilot conversation* is actually on. Not a preference: it is the
# browser's real state, and the driver compares against it to decide whether the
# picker needs touching. Conflating this with the requested default makes the
# driver skip the picker and quietly answer as Auto.
BROWSER_DEFAULT_TONE = "Magic"


def highest_gpt_tone(tones: dict = TONES) -> str:
    """The newest named GPT, computed rather than hardcoded.

    The menu is a moving target -- Gpt_5_4_Reasoning was still in this tenant's
    chat history but had already been dropped from the picker. Deriving the
    default means the day Microsoft ships 5.7 it becomes the default with no
    edit. Reasoning beats Chat at the same version: "Think deeper" is the point.
    """
    best_key = None
    best = None
    for tone in tones:
        m = re.match(r"^Gpt_(\d+)_(\d+)_(\w+)$", tone, re.IGNORECASE)
        if not m:
            continue
        cand = (int(m.group(1)), int(m.group(2)), "reasoning" in m.group(3).lower())
        if best is None or cand > best:
            best, best_key = cand, tone
    return best_key or BROWSER_DEFAULT_TONE


# What we ask for when the caller does not specify.
DEFAULT_TONE = highest_gpt_tone()

# Bot messages that are progress chatter rather than the answer. The real reply
# arrives with no messageType at all and contentOrigin "DeepLeo".
PROGRESS_TYPES = {
    "Progress",
    "InternalLoaderMessage",
    "InternalSearchQuery",
    "InternalSearchResult",
    "RenderCardRequest",
    "SearchQuery",
    "GeneratedCode",
    "Disengaged",
}

# Copilot marks citations two different ways. `hiddenText` uses the Bing-style
# [^1^]. The streamed `text` wraps them in Unicode private-use sentinels:
# U+E200 opens, U+E202 separates, U+E201 closes. Those code points have no glyph
# in any normal font, so leaving them in means the client renders a row of tofu
# boxes -- which is exactly what happened.
#
# Written with explicit \ueNNN escapes on purpose. An earlier version embedded
# the literal characters, which are invisible to every editor and reader; they
# were silently lost in an edit and left an invalid pattern behind.
CITATION_RE = re.compile(
    "\ue200.*?\ue201"            # a complete sentinel-wrapped citation span
    "|\ue200[^\ue201]*$"         # an unterminated span at the end of a delta
    r"|\[\^\d+\^\]"                # the Bing-style marker used in hiddenText
    "|[\ue200-\ue20f]",          # any stray sentinel that escaped the above
    re.DOTALL,
)
DATA_URI_RE = re.compile(r"^data:(?P<mime>[\w.+/-]+);base64,(?P<data>.+)$", re.DOTALL)

EXTENSION_FOR_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# ImageSanitizerBingAI rejects trivially small files with InvalidRequest, so a
# caller sending an 8x8 test pixel gets a useful message instead of a silent drop.
MIN_IMAGE_BYTES = 1024


def is_chathub(url: str) -> bool:
    low = url.lower()
    return "chathub" in low or ("substrate" in low and "copilot" in low)


def is_upload(url: str) -> bool:
    return "uploadfile" in url.lower()


class CopilotDriver:
    """Owns one browser on one thread; serialises turns."""

    def __init__(self, headless: bool = False, url: str = CHAT_URL,
                 profile: str | None = None,
                 browser_channel: str | None = None,
                 browser_executable: str | None = None) -> None:
        self._url = url
        self._headless = headless
        self._profile = profile or str(default_profile_dir())
        self._browser_channel = browser_channel or os.environ.get("COPILOT_BROWSER_CHANNEL", "").strip() or None
        self._browser_executable = browser_executable or os.environ.get("COPILOT_BROWSER_EXECUTABLE", "").strip() or None
        self._commands: queue.Queue = queue.Queue()
        self._events: queue.Queue = queue.Queue()
        self._turn_lock = threading.Lock()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._socket_url: str | None = None
        self._conversation_id: str | None = None
        self._current_tone: str = BROWSER_DEFAULT_TONE
        self._cancel_requested = False
        self._uploads: queue.Queue = queue.Queue()
        self._tmpdir = Path(tempfile.mkdtemp(prefix="copilot-wire-"))
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # --- frame handling (runs on the browser thread) ----------------------

    def _on_frame(self, payload: str | bytes) -> None:
        if isinstance(payload, bytes):
            try:
                payload = payload.decode("utf-8")
            except UnicodeDecodeError:
                return
        for record in split_records(payload):
            try:
                parsed = json.loads(record)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                self._handle_record(parsed)

    def _handle_record(self, rec: dict) -> None:
        msg_type = rec.get("type")

        if msg_type == 1:
            for arg in rec.get("arguments") or []:
                if isinstance(arg, dict):
                    self._harvest(arg.get("messages"))
        elif msg_type == 2:
            item = rec.get("item")
            if isinstance(item, dict):
                self._harvest(item.get("messages"))
                result = item.get("result") or {}
                if result.get("value") not in (None, "Success"):
                    self._events.put(
                        ("error", f"{result.get('value')}: {result.get('message')}")
                    )
            self._events.put(("done", None))
        elif msg_type == 3:
            self._events.put(("done", None))

    def _harvest(self, messages: object) -> None:
        if not isinstance(messages, list):
            return
        for msg in messages:
            if not isinstance(msg, dict) or msg.get("author") != "bot":
                continue
            text = msg.get("text")
            if not isinstance(text, str) or not text:
                continue
            kind = msg.get("messageType")
            if kind in PROGRESS_TYPES:
                self._events.put(("progress", text))
            elif kind in (None, "Chat"):
                self._events.put(("text", (msg.get("messageId") or "answer", text)))

    # --- browser thread --------------------------------------------------

    def _attach(self, page) -> None:
        initial_conversation = conversation_id_from_url(page.url)
        if initial_conversation:
            self._conversation_id = initial_conversation

        def on_navigated(frame) -> None:
            try:
                if frame != page.main_frame:
                    return
                current = conversation_id_from_url(frame.url)
                if current:
                    self._conversation_id = current
            except Exception:
                return

        page.on("framenavigated", on_navigated)

        def on_websocket(ws) -> None:
            if is_chathub(ws.url):
                self._socket_url = redact_url(ws.url)
                print(f"[driver] chathub attached: {self._socket_url[:90]}", flush=True)
                def on_frame(payload) -> None:
                    current = conversation_id_from_url(page.url)
                    if current:
                        self._conversation_id = current
                    self._on_frame(payload)

                ws.on("framereceived", on_frame)

        page.on("websocket", on_websocket)

        def on_response(response) -> None:
            """Signal when an image upload settles, so sends can wait on fact."""
            if not is_upload(response.url):
                return
            try:
                payload = response.json()
            except Exception:
                self._uploads.put((False, f"HTTP {response.status}, unreadable body"))
                return
            result = (payload or {}).get("result") or {}
            if result.get("value") == "Success":
                self._uploads.put((True, payload.get("fileName") or "uploaded"))
            else:
                # fileSanitizer names which check rejected it; InvalidRequest is
                # what a too-small image gets.
                self._uploads.put(
                    (
                        False,
                        f"{result.get('value')}: {result.get('message')} "
                        f"(sanitizer={payload.get('fileSanitizer')})",
                    )
                )

        page.on("response", on_response)

    def _find_composer(self, page):
        for selector in COMPOSER_SELECTORS:
            box = page.locator(selector).first
            try:
                if box.count() and box.is_visible():
                    return box
            except Exception:
                continue
        return None

    def _wait_composer(self, page, attempts: int = 600):
        for _ in range(attempts):
            box = self._find_composer(page)
            if box is not None:
                return box
            page.wait_for_timeout(500)
        return None

    def _select_tone(self, page, tone: str) -> bool:
        """Set the picker. Returns True if the wanted entry was clicked."""
        wanted = TONES.get(tone, {}).get("label")
        if not wanted:
            return False

        trigger = None
        for selector in PICKER_SELECTORS:
            candidate = page.locator(selector).first
            try:
                if candidate.count() and candidate.is_visible():
                    trigger = candidate
                    break
            except Exception:
                continue
        if trigger is None:
            return False

        trigger.click(timeout=5000)
        page.wait_for_timeout(2500)   # the menu takes well over a second

        def items():
            found = []
            for role in ("menuitemradio", "menuitem", "option"):
                try:
                    for item in page.get_by_role(role).all():
                        try:
                            if item.is_visible():
                                flat = " ".join((item.inner_text() or "").split())
                                found.append((item, role, flat))
                        except Exception:
                            continue
                except Exception:
                    continue
            return found

        def click_match(collection) -> bool:
            for item, _role, text in collection:
                if wanted.lower() in text.lower():
                    try:
                        item.click(timeout=5000)
                        page.wait_for_timeout(900)
                        return True
                    except Exception:
                        continue
            return False

        current = items()
        if click_match(current):
            return True

        # Named models sit behind a provider submenu that opens on HOVER.
        # Clicking the parent collapses it and loses the nested entries.
        for item, role, text in current:
            if role == "menuitem" and ("gpt" in text.lower() or "openai" in text.lower()):
                try:
                    item.hover()
                    page.wait_for_timeout(2200)
                except Exception:
                    continue
                if click_match(items()):
                    return True

        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    def _attach_images(self, page, data_uris: list[str]) -> None:
        """Attach images through Copilot's own file input.

        Deliberately not a hand-rolled POST to /m365Copilot/UploadFile. Handing
        the file to the page means the app builds the multipart body, supplies
        the conversationId and the gptv optionsSets, and carries its own auth.
        The upload is bound to the conversation server-side, which is why the
        chat frame that follows never references the file.
        """
        paths: list[str] = []
        for uri in data_uris:
            match = DATA_URI_RE.match(uri.strip())
            if not match:
                self._events.put(("progress", "[skipped an attachment: not a base64 data: URI]\n"))
                continue
            try:
                raw = base64.b64decode(match.group("data"), validate=False)
            except Exception:
                self._events.put(("progress", "[skipped an attachment: undecodable base64]\n"))
                continue
            if len(raw) < MIN_IMAGE_BYTES:
                self._events.put(
                    ("progress",
                     f"[skipped an attachment: {len(raw)} bytes is below the "
                     f"sanitizer's floor and would be rejected]\n")
                )
                continue
            suffix = EXTENSION_FOR_MIME.get(match.group("mime").lower(), ".png")
            path = self._tmpdir / f"upload-{int(time.time()*1000)}-{len(paths)}{suffix}"
            path.write_bytes(raw)
            paths.append(str(path))

        if not paths:
            return

        file_input = page.locator('input[type="file"]').first
        try:
            if not file_input.count():
                self._events.put(("progress", "[no file input on the page; attachment dropped]\n"))
                return
            while not self._uploads.empty():
                self._uploads.get_nowait()
            file_input.set_input_files(paths)
        except Exception as exc:
            self._events.put(("progress", f"[attach failed: {exc!r}]\n"))
            return

        # Wait for one settle signal per file rather than sleeping and hoping.
        for _ in paths:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    ok, detail = self._uploads.get_nowait()
                except queue.Empty:
                    page.wait_for_timeout(200)   # keeps Playwright events pumping
                    continue
                if ok:
                    print(f"[driver] uploaded {detail}", flush=True)
                    self._events.put(("progress", f"[attached {detail}]\n"))
                else:
                    print(f"[driver] upload rejected: {detail}", flush=True)
                    self._events.put(("progress", f"[upload rejected: {detail}]\n"))
                break
            else:
                self._events.put(("progress", "[upload did not settle in 90s]\n"))

        # The composer often needs a moment before it accepts typing again.
        page.wait_for_timeout(1200)

    def _run(self) -> None:
        try:
            with sync_playwright() as pw:
                launch_options = {
                    "headless": self._headless,
                    "viewport": {"width": 1500, "height": 950},
                }
                if self._browser_channel and self._browser_channel.lower() not in {"chromium", "bundled"}:
                    launch_options["channel"] = self._browser_channel
                if self._browser_executable:
                    launch_options["executable_path"] = self._browser_executable
                context = pw.chromium.launch_persistent_context(
                    user_data_dir=self._profile,
                    **launch_options,
                )
                page = context.pages[0] if context.pages else context.new_page()
                self._attach(page)
                context.on("page", self._attach)
                page.goto(self._url, wait_until="domcontentloaded")

                if self._wait_composer(page) is None:
                    raise RuntimeError(
                        "No Copilot composer found after waiting for sign-in. Run the packaged "
                        "`login` command and finish Microsoft sign-in in the browser window."
                    )
                page.wait_for_timeout(2000)
                self._ready.set()

                while True:
                    # Playwright's sync API dispatches event callbacks only while
                    # this thread is inside a Playwright call. Blocking on
                    # queue.get() here silently starves every "framereceived"
                    # handler, so the reply frames never arrive. Poll the queue
                    # and spend the idle time inside wait_for_timeout, which
                    # pumps the event loop.
                    try:
                        command = self._commands.get_nowait()
                    except queue.Empty:
                        try:
                            page.wait_for_timeout(150)
                        except Exception:
                            break
                        continue
                    if command is None:
                        break
                    text, tone, images, requested_conversation_id = command

                    if requested_conversation_id != self._conversation_id:
                        target = (
                            conversation_url(requested_conversation_id)
                            if requested_conversation_id
                            else self._url
                        )
                        page.goto(target, wait_until="domcontentloaded")
                        if self._wait_composer(page) is None:
                            self._events.put(("error", "composer lost while selecting conversation"))
                            self._events.put(("done", None))
                            continue
                        page.wait_for_timeout(1200)
                        self._conversation_id = requested_conversation_id

                    # tone is per-conversation, so a change needs a fresh chat.
                    if tone != self._current_tone:
                        page.goto(self._url, wait_until="domcontentloaded")
                        if self._wait_composer(page) is None:
                            self._events.put(("error", "composer lost after reload"))
                            self._events.put(("done", None))
                            continue
                        page.wait_for_timeout(2500)
                        print(f"[driver] switching tone -> {tone}", flush=True)
                        if self._select_tone(page, tone):
                            self._current_tone = tone
                            print(f"[driver] tone now {tone}", flush=True)
                        else:
                            self._events.put(
                                ("progress", f"[could not select {tone}; using current]\n")
                            )
                            self._current_tone = BROWSER_DEFAULT_TONE

                    if images:
                        self._attach_images(page, images)

                    composer = self._find_composer(page)
                    if composer is None:
                        self._events.put(("error", "composer vanished"))
                        self._events.put(("done", None))
                        continue
                    try:
                        composer.click()
                        try:
                            composer.fill("")
                        except Exception:
                            page.keyboard.press("Control+A")
                            page.keyboard.press("Delete")
                        composer.type(text, delay=8)
                        page.keyboard.press("Enter")
                    except Exception as exc:
                        self._events.put(("error", f"send failed: {exc!r}"))
                        self._events.put(("done", None))

                context.close()
        except BaseException as exc:
            self._error = exc
            self._ready.set()
            self._events.put(("error", repr(exc)))
            self._events.put(("done", None))

    # --- public API ------------------------------------------------------

    def wait_ready(self, timeout: float = 300.0) -> None:
        if not self._ready.wait(timeout):
            raise TimeoutError("browser did not become ready")
        if self._error is not None:
            raise self._error

    @property
    def socket_url(self) -> str | None:
        return self._socket_url

    @property
    def current_tone(self) -> str:
        return self._current_tone

    @property
    def conversation_id(self) -> str | None:
        return self._conversation_id

    def is_alive(self) -> bool:
        return self._thread.is_alive() and self._error is None

    def cancel(self) -> bool:
        self._cancel_requested = True
        return True

    def prompt(self, text: str, tone: str = DEFAULT_TONE,
               images: list[str] | None = None,
               conversation_id: str | None = None,
               timeout: float = 300.0) -> Iterator[tuple[str, str]]:
        """Send one prompt; yield ("text"|"reasoning", delta) as it arrives.

        Copilot re-sends the whole message body as it grows rather than emitting
        pure deltas, so the longest prefix seen per message id is tracked and only
        the new tail is yielded.
        """
        self.wait_ready()
        with self._turn_lock:
            self._cancel_requested = False
            while not self._events.empty():
                try:
                    self._events.get_nowait()
                except queue.Empty:
                    break

            if conversation_id is not None and not CONVERSATION_ID_RE.fullmatch(conversation_id):
                raise ValueError("invalid Copilot conversation id")
            self._commands.put((text, tone, images or [], conversation_id))
            deadline = time.monotonic() + timeout
            emitted: dict[str, str] = {}
            progress_seen: set[str] = set()
            got_answer = False

            while True:
                if self._cancel_requested:
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("no completion frame before timeout")
                try:
                    kind, value = self._events.get(timeout=min(remaining, 1.0))
                except queue.Empty:
                    continue

                if kind == "text":
                    message_id, full = value
                    full = CITATION_RE.sub("", full)
                    previous = emitted.get(message_id, "")
                    if full.startswith(previous):
                        tail = full[len(previous):]
                    else:
                        tail = full
                    if tail:
                        emitted[message_id] = full
                        got_answer = True
                        yield ("text", tail)
                elif kind == "progress":
                    if value not in progress_seen:
                        progress_seen.add(value)
                        yield ("reasoning", value + "\n")
                elif kind == "error":
                    if not got_answer:
                        raise RuntimeError(f"driver error: {value}")
                elif kind == "done":
                    return

    def close(self) -> None:
        self._commands.put(None)
