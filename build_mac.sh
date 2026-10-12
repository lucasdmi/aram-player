#!/bin/bash
# Builds "ARAM Player.app" and "ARAM-Player-mac.dmg" in ./dist  (run on a Mac)
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv-build
source .venv-build/bin/activate
pip install --upgrade pip -q
pip install -r requirements-app.txt -q
rm -rf build dist
pyinstaller --noconfirm --windowed --name "ARAM Player" \
  --add-data "aram_player/static:aram_player/static" --add-data "aram_player/demo:aram_player/demo" \
  --collect-all curl_cffi --collect-submodules anthropic --collect-submodules webview \
  "ARAM Player.py"
hdiutil create -volname "ARAM Player" -srcfolder "dist/ARAM Player.app" -ov -format UDZO "dist/ARAM-Player-mac.dmg"
echo
echo "Done: dist/ARAM Player.app  and  dist/ARAM-Player-mac.dmg"
