import unittest

from server.prompt import content_images, messages_to_prompt_and_images
from server.schemas import ChatMessage


class PromptImageTests(unittest.TestCase):
    def test_preserves_text_and_inline_image_for_browser_upload(self):
        image = "data:image/png;base64,aGVsbG8="
        messages = [
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": "Inspect this receipt."},
                    {"type": "image_url", "image_url": {"url": image}},
                ],
            )
        ]
        prompt, images = messages_to_prompt_and_images(messages)
        self.assertEqual(prompt, "Inspect this receipt.")
        self.assertEqual(images, [image])

    def test_does_not_fetch_remote_image_urls(self):
        content = [
            {"type": "image_url", "image_url": {"url": "https://example.test/private.png"}},
            {"type": "image_url", "image_url": "data:image/jpeg;base64,Zm9v"},
        ]
        self.assertEqual(content_images(content), ["data:image/jpeg;base64,Zm9v"])


if __name__ == "__main__":
    unittest.main()
