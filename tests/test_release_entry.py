import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import release_entry


class ReleaseEntryTests(unittest.TestCase):
    def test_configures_explicit_eve_owned_session_and_edge_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = release_entry._parser().parse_args([
                "login",
                "--session-dir", tmp,
                "--browser-channel", "msedge",
            ])
            with patch.dict(os.environ, {}, clear=False):
                result = release_entry._configure_runtime(args)
                self.assertEqual(result, Path(tmp).resolve())
                self.assertEqual(os.environ["COPILOT_SESSION_DIR"], str(Path(tmp).resolve()))
                self.assertEqual(os.environ["COPILOT_BROWSER_CHANNEL"], "msedge")

    def test_explicit_profile_dir_is_forwarded_without_copying_profile_state(self):
        with tempfile.TemporaryDirectory() as session_tmp, tempfile.TemporaryDirectory() as profile_tmp:
            args = release_entry._parser().parse_args([
                "serve",
                "--session-dir", session_tmp,
                "--profile-dir", profile_tmp,
            ])
            with patch.dict(os.environ, {}, clear=False):
                result = release_entry._configure_runtime(args)
                self.assertEqual(result, Path(session_tmp).resolve())
                self.assertEqual(os.environ["COPILOT_SESSION_DIR"], str(Path(session_tmp).resolve()))
                self.assertEqual(os.environ["COPILOT_PROFILE_DIR"], str(Path(profile_tmp).resolve()))

    def test_portable_default_uses_bundled_browser(self):
        args = release_entry._parser().parse_args(["serve"])
        self.assertEqual(args.browser_channel, "bundled")
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8000)


if __name__ == "__main__":
    unittest.main()
