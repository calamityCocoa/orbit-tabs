"""Shared paths and platform startup settings for Orbit Tabs."""
from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ORIGIN = "https://orbitlearning.app"
WEEK = 7 * 24 * 60 * 60
PLAYER = re.compile(r"/course-player/([A-Za-z0-9_-]{1,100})/([A-Za-z0-9_-]{1,100})")
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,100}")
SCRIPT = Path(__file__).resolve().with_name("orbit-course-qa.user.js")
CAMERAS = {
    "meow": ("meow.camera", "https://meow.camera/"),
    "kittens": ("Kitten Rescue Cam", "https://explore.org/livecams/cats/kitten-rescue-cam"),
}



def data_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "OrbitTabs"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/OrbitTabs"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "orbit-tabs"


def read_config(path: Path) -> dict:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        return config if isinstance(config, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(config, handle, indent=2)
            handle.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def login_entry(enable: bool, script: Path) -> None:
    executable = Path(sys.executable)
    if sys.platform == "win32" and executable.with_name("pythonw.exe").exists():
        executable = executable.with_name("pythonw.exe")
    if sys.platform == "win32" and executable.name.lower() == "orbit tabs.exe":
        command = [str(executable), "--startup"]
    else:
        command = [str(executable), str(script.resolve()), "--startup"]
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                           access=winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, "OrbitTabs", 0, winreg.REG_SZ, subprocess.list2cmdline(command))
            else:
                try:
                    winreg.DeleteValue(key, "OrbitTabs")
                except FileNotFoundError:
                    pass
        return
    if sys.platform == "darwin":
        path = Path.home() / "Library/LaunchAgents/local.orbit-tabs.plist"
        content = plistlib.dumps({"Label": "local.orbit-tabs", "ProgramArguments": command, "RunAtLoad": True})
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart/orbit-tabs.desktop"
        # Desktop Entry uses double quotes, with shell expansion disabled by the desktop launcher.
        args = " ".join('"' + re.sub(r'([\\"$`])', r'\\\1', arg).replace("%", "%%") + '"' for arg in command)
        content = ("[Desktop Entry]\nType=Application\nName=Orbit Tabs\n"
                   f"Exec={args}\nTerminal=false\n").encode()
    if enable:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    else:
        path.unlink(missing_ok=True)



def clock_text(seconds: float) -> str:
    hours, remaining = divmod(max(0, int(seconds)), 3600)
    minutes, seconds = divmod(remaining, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
