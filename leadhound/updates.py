"""Update check (PyPI, then GitHub Releases) and one-click upgrade for pip/pipx installs."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

from . import __version__

PYPI = "https://pypi.org/pypi/leadhound/json"
GITHUB = "https://api.github.com/repos/kalidatuna/leadhound/releases/latest"
# Installs and upgrades come straight from this repository's release archives, never from a package
# name lookup, so nobody else's package can be installed by mistake.
ARCHIVE = "https://github.com/kalidatuna/leadhound/archive/refs/tags/v{version}.zip"
RELEASES_PAGE = "https://github.com/kalidatuna/leadhound/releases/latest"
CACHE_SECONDS = 12 * 3600


def install_mode() -> str:
    """frozen (downloaded app file) | cloud (Docker / server) | source (git checkout) | pip."""
    if getattr(sys, "frozen", False):
        return "frozen"
    if os.environ.get("LEADHOUND_CLOUD") or os.path.exists("/.dockerenv"):
        return "cloud"
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isdir(os.path.join(here, ".git")):
        return "source"
    return "pip"


def parse_version(v: str) -> tuple:
    nums = re.findall(r"\d+", (v or "").split("+")[0])[:3]
    return tuple(int(n) for n in nums) + (0,) * (3 - len(nums))


def check(fetcher, cache_path: str, force: bool = False) -> dict:
    info = {"current": __version__, "latest": None, "newer": False, "mode": install_mode(), "url": RELEASES_PAGE}
    try:
        with open(cache_path, encoding="utf-8") as f:
            cached = json.load(f)
        if not force and time.time() - cached.get("checked", 0) < CACHE_SECONDS:
            info["latest"] = cached.get("latest")
    except (OSError, ValueError):
        pass
    if info["latest"] is None:
        latest = None
        try:
            latest = fetcher.get_json(GITHUB, headers={"Accept": "application/vnd.github+json"})["tag_name"].lstrip("v")
        except Exception:
            try:
                latest = fetcher.get_json(PYPI)["info"]["version"]
            except Exception:
                latest = None
        if latest:
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump({"latest": latest, "checked": time.time()}, f)
            except OSError:
                pass
        info["latest"] = latest
    info["newer"] = bool(info["latest"]) and parse_version(info["latest"]) > parse_version(__version__)
    return info


def upgrade(log, version: str) -> bool:
    """pip install the release archive into the running environment. Returns True on success."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version or ""):
        log(f"no valid version to install: {version!r}")
        return False
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", ARCHIVE.format(version=version)]
    log("running: " + " ".join(cmd[2:]))
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except OSError as e:
        log(f"could not start pip: {e}")
        return False
    for line in p.stdout:
        if line.strip():
            log(line.rstrip())
    return p.wait() == 0


def restart_command(port: int) -> list:
    return [sys.executable, "-m", "leadhound", "serve", "--port", str(port), "--no-browser"]


def restart(port: int) -> None:
    """Replace this process with a fresh leadhound on the same port (open sockets close on exec)."""
    sys.stdout.flush()
    os.execv(sys.executable, restart_command(port))
