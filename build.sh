#!/bin/sh
# Builds dist/MultiBuilder (Linux) or dist/MultiBuilder.app (macOS). Needs Python 3.10+ with Tk, and git.
set -e
cd "$(dirname "$0")"
git submodule update --init
python3 -m pip install -r requirements.txt
python3 -m PyInstaller --noconfirm MultiBuilder.spec
