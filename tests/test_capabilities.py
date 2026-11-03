"""Deterministic capability/model routing tests."""

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from copilot.auth import auth_from_token_response
from copilot.capabilities import (
    available_models,
    resolve_model,
    save_discovered_models,
)
from copilot.protocol import chat_frame
from copilot.client import CopilotClient
from copilot.browser import BrowserCopilot
from copilot.protocol import MSA_TENANT


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

    def test_browser_needs_actual_work_chathub_route_not_just_a_token(self):
        self.assertFalse(BrowserCopilot._has_verified_routing({
            "access_token": "opaque", "tenant": "work-tenant"
        }))
        self.assertTrue(BrowserCopilot._has_verified_routing({
            "access_token": "opaque",
            "tenant": "work-tenant",
            "scenario": "OfficeWebIncludedCopilot",
            "license_type": "Starter",
        }))
        self.assertTrue(BrowserCopilot._has_verified_routing({
            "access_token": "opaque", "tenant": MSA_TENANT
        }))

    def test_picker_discovery_controls_named_models(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "capabilities.json")
            initial = [model.id for model in available_models(path, account_key="free-a")]
            self.assertEqual(initial, ["copilot", "quick", "think-deeper"])

            saved = save_discovered_models(
                ["Auto", "Quick response", "Think deeper", "GPT 5.6 Think deeper"],
                path, account_key="free-a",
            )
            self.assertIn("gpt-5.6-think-deeper", saved)
            self.assertEqual(
                resolve_model("gpt-5.6-think-deeper", path, account_key="free-a").tone,
                "Gpt_5_6_Reasoning",
            )
            other = [model.id for model in available_models(path, account_key="work-b")]
            self.assertNotIn("gpt-5.6-think-deeper", other)
            self.assertEqual(other, ["copilot", "quick", "think-deeper"])

    def test_unknown_picker_label_is_not_silently_advertised(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "capabilities.json")
            with self.assertRaises(ValueError):
                save_discovered_models(
                    ["Definitely Not A Real Model"], path, account_key="free-a"
                )

    def test_chat_frame_uses_requested_tone(self):
        frame = chat_frame(
            "hello", "request", "session", True, tone="Gpt_5_6_Reasoning"
        )
        self.assertEqual(frame["arguments"][0]["tone"], "Gpt_5_6_Reasoning")

    def test_work_account_without_routing_proof_does_not_borrow_free_scenario(self):
        client = CopilotClient(interactive_clear=False)
        with patch.object(client, "_fresh_auth", return_value={
            "access_token": "opaque-token",
            "oid": "work-account",
            "tenant": "work-tenant",
        }):
            with self.assertRaisesRegex(RuntimeError, "consumer-Free route is not used"):
                list(client.stream("Hello", model="copilot"))

    def test_consumer_auto_uses_exact_account_tenant_and_model_tone(self):
        client = CopilotClient(interactive_clear=False)
        calls = []
        def driver(_prompt, **kwargs):
            calls.append(kwargs)
            yield "OK"
        with patch.object(client, "_fresh_auth", return_value={
            "access_token": "opaque-token",
            "oid": "consumer-account",
            "tenant": MSA_TENANT,
        }), patch.object(client._driver, "create_completion", side_effect=driver):
            self.assertEqual(list(client.stream("Hello", model="think-deeper")), ["OK"])
        self.assertEqual(calls[0]["tenant"], MSA_TENANT)
        self.assertEqual(calls[0]["tone"], "Gpt_5_5_Reasoning")
        self.assertNotIn("browser", calls[0])


if __name__ == "__main__":
    unittest.main()
