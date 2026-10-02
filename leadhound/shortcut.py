"""Create a double-click launcher so leadhound opens without typing commands."""
from __future__ import annotations

import os
import stat
import sys


def _desktop() -> str:
    d = os.path.join(os.path.expanduser("~"), "Desktop")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def build(platform: str, python: str) -> tuple[str, str, bool]:
    """Return (file name, contents, make_executable) for a platform ('linux', 'darwin' or 'win32')."""
    if platform.startswith("win"):
        return "leadhound.bat", f'@echo off\r\ntitle leadhound\r\n"{python}" -m leadhound\r\npause\r\n', False
    if platform == "darwin":
        return "leadhound.command", f'#!/bin/bash\nexec "{python}" -m leadhound\n', True
    return ("leadhound.desktop",
            "[Desktop Entry]\nType=Application\nName=leadhound\nComment=Find freelance clients\n"
            f'Exec="{python}" -m leadhound\nTerminal=true\nCategories=Office;Network;\n', True)


def create(platform: str | None = None, python: str | None = None, folder: str | None = None) -> str:
    name, text, executable = build(platform or sys.platform, python or sys.executable)
    folder = folder or _desktop()
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path
