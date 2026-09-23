import unittest
from unittest.mock import patch

from copilot.browser import BrowserCopilot


class _FakePage:
    def __init__(self):
        self.calls = []

    def set_default_timeout(self, value):
        self.calls.append(("timeout", value))

    def goto(self, url, **kwargs):
        self.calls.append(("goto", url, kwargs))
        if kwargs.get("wait_until") != "domcontentloaded":
            raise AssertionError("startup must not wait for networkidle")


class _FakeContext:
    def __init__(self, page):
        self.pages = [page]
        self.closed = False

    def close(self):
        self.closed = True


class _FakePlaywright:
    def __init__(self, context):
        self.chromium = self
        self.context = context
        self.stopped = False

    def launch_persistent_context(self, profile, **kwargs):
        return self.context

    def stop(self):
        self.stopped = True


class _FakePlaywrightFactory:
    def __init__(self, playwright):
        self.playwright = playwright

    def start(self):
        return self.playwright


class BrowserStartupRegressionTests(unittest.TestCase):
    def test_start_does_not_wait_for_networkidle(self):
        page = _FakePage()
        context = _FakeContext(page)
        playwright = _FakePlaywright(context)
        driver = BrowserCopilot(profile_dir="test-profile")

        with patch("copilot.browser.sync_playwright", return_value=_FakePlaywrightFactory(playwright)):
            driver.start()

        self.assertEqual(page.calls[1][0], "goto")
        self.assertEqual(page.calls[1][2]["wait_until"], "domcontentloaded")
        driver.close()
        self.assertTrue(context.closed)
        self.assertTrue(playwright.stopped)


if __name__ == "__main__":
    unittest.main()
