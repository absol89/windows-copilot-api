"""Deterministic capability/model routing tests."""

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path

from copilot.auth import auth_from_token_response
from copilot.capabilities import (
    available_models,
    resolve_model,
    save_discovered_models,
)
from copilot.protocol import chat_frame


def _token(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"x.{payload}.x"


class CapabilityTests(unittest.TestCase):
    def test_auth_snapshot_keeps_real_tenant(self):
        auth = auth_from_token_response(
            {
                "access_token": _token({"tid": "tenant-work"}),
                "refresh_token": "r",
                "expires_in": 60,
            },
            "oid",
            "Oid:oid@anchor-tenant",
            time.time(),
            token_url="https://login.microsoftonline.com/tenant-work/oauth2/v2.0/token",
        )
        self.assertEqual(auth["tenant"], "anchor-tenant")
        self.assertIn("tenant-work", auth["token_url"])

    def test_picker_discovery_controls_named_models(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "capabilities.json")
            initial = [model.id for model in available_models(path)]
            self.assertEqual(initial, ["copilot", "quick", "think-deeper"])

            saved = save_discovered_models(
                ["Auto", "Quick response", "Think deeper", "GPT 5.6 Think deeper"],
                path,
            )
            self.assertIn("gpt-5.6-think-deeper", saved)
            self.assertEqual(
                resolve_model("gpt-5.6-think-deeper", path).tone,
                "Gpt_5_6_Reasoning",
            )

    def test_unknown_picker_label_is_not_silently_advertised(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "capabilities.json")
            with self.assertRaises(ValueError):
                save_discovered_models(["Definitely Not A Real Model"], path)

    def test_chat_frame_uses_requested_tone(self):
        frame = chat_frame(
            "hello", "request", "session", True, tone="Gpt_5_6_Reasoning"
        )
        self.assertEqual(frame["arguments"][0]["tone"], "Gpt_5_6_Reasoning")


if __name__ == "__main__":
    unittest.main()
