#!/bin/sh
# leadhound installer for macOS and Linux. Run:
#   curl -fsSL https://raw.githubusercontent.com/kalidatuna/leadhound/main/install.sh | sh
#
# What it does: finds Python 3.10+, creates a private environment in ~/.leadhound/app,
# installs leadhound there, adds the `leadhound` command and a desktop icon, then opens the app.
# Nothing is installed system-wide and no admin rights are needed.
# Options (environment variables): LEADHOUND_HOME, LEADHOUND_NO_START=1, LEADHOUND_SOURCE (pip spec or folder).
# leadhound is downloaded straight from its GitHub repository.
set -eu

APP_HOME="${LEADHOUND_HOME:-$HOME/.leadhound}"
VENV="$APP_HOME/app"
SRC="${LEADHOUND_SOURCE:-https://github.com/kalidatuna/leadhound/archive/refs/heads/main.zip}"
BIN_DIR="$HOME/.local/bin"
RELEASES="https://github.com/kalidatuna/leadhound/releases/latest"

say() { printf '%s\n' "$*"; }

find_python() {
  for p in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$p" >/dev/null 2>&1 &&
       "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

if ! PY=$(find_python); then
  say "leadhound needs Python 3.10 or newer, and none was found."
  case "$(uname -s)" in
    Darwin) say "Install it with:  brew install python   (or from https://www.python.org/downloads/)" ;;
    *) say "Install it with your package manager, e.g.:  sudo apt install python3 python3-venv" ;;
  esac
  say "Or download the ready-made app instead: $RELEASES"
  exit 1
fi
say "Using $("$PY" --version 2>&1)"

mkdir -p "$APP_HOME"
if ! "$PY" -m venv "$VENV" >/dev/null 2>&1; then
  say "Python's venv module is missing. On Debian/Ubuntu run:  sudo apt install python3-venv"
  exit 1
fi

say "Installing leadhound (about 30 seconds)..."
if ! "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade "$SRC"; then
  say "Download failed. Check your internet connection and run the installer again."
  exit 1
fi

mkdir -p "$BIN_DIR"
ln -sf "$VENV/bin/leadhound" "$BIN_DIR/leadhound"
if "$VENV/bin/leadhound" shortcut >/dev/null 2>&1; then
  say "Desktop icon created."
fi

say ""
say "leadhound $("$VENV/bin/leadhound" --version | cut -d' ' -f2) is installed."
case ":$PATH:" in
  *":$BIN_DIR:"*) say "Open it any time with:  leadhound" ;;
  *) say "Open it any time with:  $BIN_DIR/leadhound   (add $BIN_DIR to your PATH to type just 'leadhound')" ;;
esac

if [ -z "${LEADHOUND_NO_START:-}" ]; then
  say "Opening leadhound in your browser now. Close this window to stop it."
  exec "$VENV/bin/leadhound"
fi
