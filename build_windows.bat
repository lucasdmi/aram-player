@echo off
REM Builds dist\ARAM Player\ARAM Player.exe and ARAM-Player-windows.zip (run on Windows)
python -m venv .venv-build
call .venv-build\Scripts\activate
pip install -r requirements-app.txt
rmdir /s /q build dist 2>nul
pyinstaller --noconfirm --windowed --name "ARAM Player" --add-data "aram_player/static;aram_player/static" --add-data "aram_player/demo;aram_player/demo" --collect-all curl_cffi --collect-submodules anthropic --collect-submodules webview "ARAM Player.py"
powershell -Command "Compress-Archive -Force -Path 'dist\ARAM Player' -DestinationPath 'dist\ARAM-Player-windows.zip'"
echo Done: dist\ARAM-Player-windows.zip
