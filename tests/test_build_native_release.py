import unittest
from unittest.mock import patch
from pathlib import Path

from scripts import build_native_release


class BuildNativeReleaseTests(unittest.TestCase):
    def test_build_info_declares_stable_bridge_capabilities(self):
        with patch.object(build_native_release, "git_commit", return_value="test-commit"):
            info = build_native_release.build_info("windows-copilot-api.exe")

        self.assertEqual(
            info["capabilities"],
            [
                "explicit-profile-dir",
                "conversation-continuation",
                "image-url-input",
            ],
        )
        self.assertEqual(info["default_copilot_url"], "https://copilot.cloud.microsoft/chat")

    def test_default_browser_payload_is_repo_playwright_browsers(self):
        with patch.dict(build_native_release.os.environ, {}, clear=True):
            configured = build_native_release.os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
            browser_root = (
                Path(configured).expanduser()
                if configured
                else build_native_release.ROOT / ".playwright-browsers"
            )
        self.assertEqual(browser_root, build_native_release.ROOT / ".playwright-browsers")


if __name__ == "__main__":
    unittest.main()
