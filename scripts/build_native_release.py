"""Build and archive one native Windows Copilot API release bundle."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist" / "windows-copilot-api"
RELEASE = ROOT / "release"
VERSION = os.environ.get("WINDOWS_COPILOT_API_VERSION", "1.0.0").strip() or "1.0.0"
CAPABILITIES = [
    "explicit-profile-dir",
    "conversation-continuation",
    "image-url-input",
]


def run(*args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=ROOT, env=env, check=True)


def normalized_platform() -> str:
    return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(platform.system(), platform.system().lower())


def normalized_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "x64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine.replace(" ", "-")


def git_commit() -> str:
    override = os.environ.get("WINDOWS_COPILOT_API_SOURCE_COMMIT", "").strip()
    if override:
        return override
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def build_info(executable_name: str) -> dict[str, object]:
    return {
        "name": "windows-copilot-api",
        "version": VERSION,
        "source_commit": git_commit(),
        "platform": normalized_platform(),
        "arch": normalized_arch(),
        "python": platform.python_version(),
        "portable": True,
        "entrypoint": executable_name,
        "commands": ["login", "serve"],
        "capabilities": list(CAPABILITIES),
        "default_copilot_url": "https://copilot.cloud.microsoft/chat",
        "bundled_browser_dir": "playwright-browsers",
    }


def main() -> None:
    if VERSION.startswith("v") or VERSION.count(".") != 2:
        raise SystemExit(
            "WINDOWS_COPILOT_API_VERSION must be a plain semantic tag such as 1.0.0 (no v prefix)"
        )
    env = os.environ.copy()
    configured_browser_root = env.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    browser_root = (
        Path(configured_browser_root).expanduser()
        if configured_browser_root
        else ROOT / ".playwright-browsers"
    )
    if not browser_root.is_absolute():
        browser_root = (ROOT / browser_root).resolve()
    if not browser_root.is_dir():
        raise SystemExit(
            f"Playwright browser payload is missing at {browser_root}. "
            "Install it first with PLAYWRIGHT_BROWSERS_PATH=<that folder> python -m playwright install chromium"
        )
    if not any(path.is_dir() and path.name.startswith("chromium-") for path in browser_root.iterdir()):
        raise SystemExit(
            f"Playwright Chromium payload is missing at {browser_root}. "
            "Install it first with PLAYWRIGHT_BROWSERS_PATH=<that folder> python -m playwright install chromium"
        )
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_root)
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "windows_copilot_api.spec", env=env)

    executable = DIST / ("windows-copilot-api.exe" if os.name == "nt" else "windows-copilot-api")
    if not executable.is_file():
        raise SystemExit(f"PyInstaller did not create {executable}")
    bundled_browsers = DIST / "playwright-browsers"
    if bundled_browsers.exists():
        shutil.rmtree(bundled_browsers)
    # Preserve browser-bundle symlinks. This matters on macOS, where Chromium's
    # .app framework uses symlinks that should remain symlinks in the archive.
    shutil.copytree(browser_root, bundled_browsers, symlinks=True)

    info = build_info(executable.name)
    (DIST / "BUILD-INFO.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    run(str(executable), "--version", env=env)

    RELEASE.mkdir(parents=True, exist_ok=True)
    base = RELEASE / f"windows-copilot-api-{VERSION}-{info['platform']}-{info['arch']}"
    if info["platform"] == "windows":
        archive = shutil.make_archive(str(base), "zip", DIST.parent, DIST.name)
    else:
        archive = shutil.make_archive(str(base), "gztar", DIST.parent, DIST.name)
    print(f"release={archive}")


if __name__ == "__main__":
    main()
