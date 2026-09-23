"""Portable native entry point used by PyInstaller release bundles."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sys


DEFAULT_APP_VERSION = "1.0.0"


def _app_version() -> str:
    if getattr(sys, "frozen", False):
        build_info = Path(sys.executable).resolve().parent / "BUILD-INFO.json"
        try:
            version = json.loads(build_info.read_text(encoding="utf-8")).get("version", "")
            if isinstance(version, str) and version.strip():
                return version.strip()
        except (OSError, json.JSONDecodeError):
            pass
    return DEFAULT_APP_VERSION


APP_VERSION = _app_version()


def _default_session_dir() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / "WindowsCopilotAPI" / "session"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "WindowsCopilotAPI" / "session"
    root = os.environ.get("XDG_STATE_HOME")
    return Path(root) / "windows-copilot-api" if root else Path.home() / ".local" / "state" / "windows-copilot-api"


def _configure_runtime(args: argparse.Namespace) -> Path:
    session_dir = Path(args.session_dir or _default_session_dir()).expanduser().resolve()
    session_dir.mkdir(parents=True, exist_ok=True)
    os.environ["COPILOT_SESSION_DIR"] = str(session_dir)
    if args.profile_dir:
        profile_dir = Path(args.profile_dir).expanduser().resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        os.environ["COPILOT_PROFILE_DIR"] = str(profile_dir)
    else:
        os.environ.pop("COPILOT_PROFILE_DIR", None)
    if args.browser_channel:
        os.environ["COPILOT_BROWSER_CHANNEL"] = args.browser_channel
    if args.browser_channel in {"bundled", "chromium"} and getattr(sys, "frozen", False):
        bundled_browsers = Path(sys.executable).resolve().parent / "playwright-browsers"
        if bundled_browsers.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundled_browsers)
    if args.browser_executable:
        os.environ["COPILOT_BROWSER_EXECUTABLE"] = str(Path(args.browser_executable).expanduser().resolve())
    if args.chat_url:
        os.environ["COPILOT_CHAT_URL"] = args.chat_url
    return session_dir


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="windows-copilot-api")
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--session-dir", help="Writable folder for the persistent Copilot browser profile")
    common.add_argument(
        "--profile-dir",
        help=(
            "Exact persistent Chromium profile directory. Managed hosts may use this to select "
            "an Eve-owned profile or an explicitly chosen user profile without copying profile state."
        ),
    )
    common.add_argument(
        "--browser-channel",
        choices=("chromium", "bundled", "msedge", "chrome", "chrome-beta", "msedge-beta", "msedge-dev"),
        default="bundled",
        help="Browser used by Playwright; bundled Chromium is the portable default",
    )
    common.add_argument("--browser-executable", help="Explicit Chromium-family browser executable")
    common.add_argument("--chat-url", default="https://copilot.cloud.microsoft/chat")

    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", parents=[common], help="Open the persistent Copilot browser and wait for sign-in")
    login.add_argument("--timeout", type=float, default=300.0)
    serve = commands.add_parser("serve", parents=[common], help="Run the local OpenAI-compatible bridge")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    session_dir = _configure_runtime(args)
    if args.command == "login":
        from copilot.m365_driver import CopilotDriver

        driver = CopilotDriver(headless=False)
        try:
            driver.wait_ready(args.timeout)
            print(f"Copilot sign-in ready; session profile is stored under {session_dir}")
            return 0
        finally:
            driver.close()
    if args.command == "serve":
        os.environ["HOST"] = args.host
        os.environ["PORT"] = str(args.port)
        from server import app

        print(
            f"Starting Windows Copilot API {APP_VERSION} on {platform.system()} {platform.machine()} "
            f"with session {session_dir}"
        )
        app(host=args.host, port=args.port)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
