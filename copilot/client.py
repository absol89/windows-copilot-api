"""High-level Copilot client — the recommended entry point.

One client, many conversations addressed by id. :meth:`CopilotClient.chat`
returns the full reply plus the conversation id; pass that id back to continue
the same conversation, or omit it to start a fresh one. :meth:`CopilotClient.stream`
is the incremental variant.

    from copilot import CopilotClient

    client = CopilotClient()                       # loads signed-in auth once
    r = client.chat("My name is Tomato. Remember it.")
    print(r.text, r.conversation_id)

    r2 = client.chat("What's my name?", r.conversation_id)   # continue
    print(r2.text)

    for chunk in client.stream("Tell me a joke"):  # new conversation, streamed
        print(chunk, end="", flush=True)

The signed-in access token is refreshed transparently; sign in once with
``python -m copilot login``. Pass ``anonymous=True`` to skip sign-in (only where
anonymous consumer chat is available), or ``proxy=...`` to route through a
supported region.
"""

from dataclasses import dataclass, field
from typing import Generator, List, Optional, Union

from .auth import AUTH_MAX_AGE
from .m365_driver import BROWSER_DEFAULT_TONE, CopilotDriver
from .models import Conversation, ImageResponse


@dataclass
class ChatReply:
    """The full result of a :meth:`CopilotClient.chat` call."""

    text: str
    conversation_id: Optional[str]
    images: List[ImageResponse] = field(default_factory=list)


class ChatStream:
    """Iterable stream of reply chunks that also exposes the conversation id.

    Yields ``str`` text chunks (and :class:`~copilot.models.ImageResponse` for
    generated images). ``conversation_id`` is known up front when continuing an
    existing conversation, and is populated as soon as iteration begins when a
    new conversation is created.
    """

    def __init__(self, chunks: Generator, conversation_id: Optional[str]):
        self._chunks = chunks
        self.conversation_id = conversation_id

    def __iter__(self) -> Generator[Union[str, ImageResponse], None, None]:
        for item in self._chunks:
            if isinstance(item, Conversation):
                self.conversation_id = item.conversation_id
            else:
                yield item


class CopilotClient:
    """A Copilot client: one object, many conversations addressed by id.

    Parameters
    ----------
    anonymous:
        Skip sign-in and talk to Copilot anonymously. Only works where the
        anonymous consumer experience is available (it is geo-blocked in some
        regions, e.g. India). Default ``False`` uses the signed-in session.
    proxy:
        Optional ``scheme://user:pass@host:port`` proxy, applied to both the
        auth refresh and every request.
    max_age:
        Seconds a cached access token is trusted before it is refreshed.
    """

    def __init__(
        self,
        anonymous: bool = False,
        proxy: Optional[str] = None,
        max_age: int = AUTH_MAX_AGE,
    ):
        # Microsoft moved the current Copilot Chat surface to the M365 web
        # application. Its chat turn is carried by the page's SignalR/Chathub
        # WebSocket, so the old curl_cffi consumer driver cannot reach it.
        self._driver = CopilotDriver(headless=False)
        self._anonymous = anonymous
        self._proxy = proxy
        self._max_age = max_age

    def stream(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        **kwargs,
    ) -> ChatStream:
        """Stream the reply to ``prompt`` as a :class:`ChatStream`.

        Starts a new conversation when ``conversation_id`` is ``None``; otherwise
        continues that conversation. Read ``.conversation_id`` on the returned
        stream (during/after iteration) to continue the chat later.
        """
        # The resident browser owns one real Copilot conversation. Keep the
        # OpenAI conversation_id as a client-side handle for compatibility; the
        # browser driver serializes turns on the authenticated session.
        tone = kwargs.pop("tone", BROWSER_DEFAULT_TONE)
        images = kwargs.pop("images", None)
        chunks = (text for kind, text in self._driver.prompt(prompt, tone=tone, images=images or []))
        return ChatStream(chunks, conversation_id)

    def chat(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        **kwargs,
    ) -> ChatReply:
        """Return the full reply to ``prompt`` as a :class:`ChatReply`.

        Buffers the whole response; use :meth:`stream` for incremental output.
        """
        s = self.stream(prompt, conversation_id=conversation_id, **kwargs)
        text: List[str] = []
        images: List[ImageResponse] = []
        for item in s:
            if isinstance(item, str):
                text.append(item)
            elif isinstance(item, ImageResponse):
                images.append(item)
        return ChatReply("".join(text), s.conversation_id, images)
