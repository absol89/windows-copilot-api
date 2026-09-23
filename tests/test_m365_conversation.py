import unittest

from copilot.client import CopilotClient
from copilot.m365_driver import CHAT_URL, conversation_id_from_url, conversation_url


CID = "5c7ca476-12e3-44a7-97e2-f1cfb03b5167"


class ConversationUrlTests(unittest.TestCase):
    def test_extracts_and_rebuilds_m365_copilot_conversation_url(self):
        url = f"{CHAT_URL.rstrip('/')}/conversation/{CID}"
        self.assertEqual(conversation_id_from_url(url), CID)
        self.assertEqual(conversation_url(CID), url)

    def test_rejects_untrusted_conversation_ids(self):
        with self.assertRaises(ValueError):
            conversation_url("../other")


class _FakeDriver:
    def __init__(self):
        self.conversation_id = CID
        self.requested = None

    def prompt(self, text, tone, images, conversation_id, timeout=300.0):
        self.requested = conversation_id
        yield ("text", "hello")


class ClientConversationTests(unittest.TestCase):
    def test_stream_forwards_requested_id_and_publishes_browser_id(self):
        client = CopilotClient.__new__(CopilotClient)
        client._driver = _FakeDriver()
        stream = client.stream("continue", conversation_id=CID)
        self.assertEqual(list(stream), ["hello"])
        self.assertEqual(client._driver.requested, CID)
        self.assertEqual(stream.conversation_id, CID)


if __name__ == "__main__":
    unittest.main()
