"""Read-only client for the League Client (LCU) local API.

Only talks to https://127.0.0.1:<port> exposed by the Riot client itself.
No process memory reading, no injection, no input automation.
"""
from __future__ import annotations

import base64
import os
import platform
import re
import subprocess
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOCKFILE_CANDIDATES = [
    os.environ.get("LOL_LOCKFILE", ""),
    "/Applications/League of Legends.app/Contents/LoL/lockfile",
    str(Path.home() / "Applications/League of Legends.app/Contents/LoL/lockfile"),
    r"C:\Riot Games\League of Legends\lockfile",
    r"D:\Riot Games\League of Legends\lockfile",
    os.path.expandvars(r"%ProgramFiles%\Riot Games\League of Legends\lockfile"),
]


def _from_process() -> tuple[int, str] | None:
    """Fallback: read --app-port / --remoting-auth-token from the client's command line."""
    try:
        if platform.system() == "Windows":
            # wmic is removed on recent Windows 11 builds -> PowerShell CIM first, wmic as fallback
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash in the packaged app
            out = ""
            for cmd in (["powershell", "-NoProfile", "-Command",
                         "Get-CimInstance Win32_Process -Filter \"name='LeagueClientUx.exe'\" | "
                         "Select-Object -ExpandProperty CommandLine"],
                        ["wmic", "PROCESS", "WHERE", "name='LeagueClientUx.exe'", "GET", "commandline"]):
                try:
                    out = subprocess.run(cmd, capture_output=True, text=True, timeout=8,
                                         creationflags=flags).stdout
                except Exception:
                    continue
                if "--app-port" in out:
                    break
            out = "\n".join("LeagueClientUx " + l for l in out.splitlines())  # lines are UX-only here
        else:
            out = subprocess.run(["ps", "-Aww", "-o", "args"],  # -ww: no truncation (macOS)
                                 capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    # Use the LeagueClientUx line only: the Riot Client launcher has its own port/token.
    for line in out.splitlines():
        if "LeagueClientUx" not in line:
            continue
        port = re.search(r"--app-port=(\d+)", line)
        token = re.search(r'--remoting-auth-token=([\w-]+)', line)
        if port and token:
            return int(port.group(1)), token.group(1)
    return None


def find_credentials() -> tuple[int, str] | None:
    for p in LOCKFILE_CANDIDATES:
        if p and Path(p).is_file():
            try:
                # name:pid:port:password:protocol
                parts = Path(p).read_text().strip().split(":")
                return int(parts[2]), parts[3]
            except Exception:
                pass
    return _from_process()


class LCU:
    def __init__(self) -> None:
        self.base: str | None = None
        self.session = requests.Session()
        self.session.verify = False

    def connect(self) -> bool:
        # scanning processes is the expensive part: at most once every 10 s
        import time as _t
        if _t.time() - getattr(self, "_last_scan", 0) < 10:
            return False
        self._last_scan = _t.time()
        creds = find_credentials()
        from .log import log
        log.info("League client %s", f"found on port {creds[0]}" if creds else "not found")
        if not creds:
            self.base = None
            return False
        port, password = creds
        self.base = f"https://127.0.0.1:{port}"
        token = base64.b64encode(f"riot:{password}".encode()).decode()
        self.session.headers["Authorization"] = f"Basic {token}"
        return True

    def get(self, path: str):
        if not self.base and not self.connect():
            return None
        try:
            r = self.session.get(self.base + path, timeout=2)
            if r.status_code == 200:
                return r.json()
            return None
        except requests.RequestException:
            self.base = None  # client closed/restarted; reconnect next time
            return None

    # --- convenience wrappers -------------------------------------------
    def phase(self) -> str | None:
        """Gameflow phase. Remembers which endpoint works on this client so each poll is 1 request."""
        mode = getattr(self, "_phase_mode", None)
        if mode in (None, "phase"):
            p = self.get("/lol-gameflow/v1/gameflow-phase")
            if isinstance(p, str):
                self._phase_mode = "phase"
                return p
        if mode in (None, "session"):
            sess = self.get("/lol-gameflow/v1/session")
            if isinstance(sess, dict) and sess.get("phase"):
                self._phase_mode = "session"
                return sess["phase"]
        if not self.base:
            self._phase_mode = None
            return None
        if self.get("/lol-champ-select/v1/session"):
            return "ChampSelect"
        return "Lobby"  # connected but phase unknown

    def alive(self) -> bool:
        try:
            self.session.get(self.base + "/riotclient/region-locale", timeout=2)
            return True
        except Exception:
            return False

    def gameflow_session(self) -> dict | None:
        return self.get("/lol-gameflow/v1/session")

    def champ_select(self) -> dict | None:
        return self.get("/lol-champ-select/v1/session")
