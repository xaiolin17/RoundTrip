#!/usr/bin/env bash
# Thin wrapper for install.py.
# Linux / macOS / Git Bash on Windows all work.
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer python3 if present; fallback to python
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Error: Python 3.10+ not found. Install it first:" >&2
  echo "  macOS:        brew install python@3.12" >&2
  echo "  Ubuntu/Debian: sudo apt install python3.10 python3.10-venv" >&2
  echo "  Fedora:       sudo dnf install python3.10" >&2
  echo "  Arch:         sudo pacman -S python" >&2
  exit 1
fi

exec "$PY" "$DIR/install.py" "$@"
