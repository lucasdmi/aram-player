"""Desktop launcher: starts ARAM Player and shows it in its own window.

Falls back to the default browser if the window library is unavailable.
"""
from __future__ import annotations

import platform
import socket
import subprocess
import sys
import time
import webbrowser


def _free_port(preferred: int = 8765) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferred


def _wait_ready(url: str, timeout: float = 60) -> None:
    import urllib.request
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url + "/api/state", timeout=1)
            return
        except Exception:
            time.sleep(0.3)


class Api:
    """Exposed to the page as window.pywebview.api.* (desktop app only)."""

    def clipboard(self) -> str:
        """Read the clipboard text: the in-app webview can't always paste on Windows."""
        try:
            if platform.system() == "Windows":
                return subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                                      capture_output=True, text=True, timeout=5,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
            if platform.system() == "Darwin":
                return subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            pass
        return ""


def run() -> None:
    from aram_player import main as core

    demo = "--demo" in sys.argv
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    core.start(port=port, demo=demo, block=False)
    _wait_ready(url)
    try:
        import webview  # pywebview
    except ImportError:
        webbrowser.open(url)
        while True:
            time.sleep(3600)
    webview.create_window("ARAM Player", url, width=520, height=900, min_size=(380, 500),
                          text_select=True, js_api=Api())   # text_select: allow selecting/pasting in inputs
    webview.start()  # returns when the window is closed -> app exits


if __name__ == "__main__":
    run()
