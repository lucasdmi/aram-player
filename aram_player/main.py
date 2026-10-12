"""ARAM Player — local build helper for ARAM / ARAM Mayhem.

Run:  python -m aram_player.main            (real client)
      python -m aram_player.main --demo     (fake game, no League needed)
Then open http://127.0.0.1:8765 (second monitor, laptop, or phone on same Wi-Fi with --lan).
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

import sys

from . import config
from .advice import AdviceEngine, Context
from .advice.claude import ClaudeAdvisor, model as ai_model, test_key
from .advice.rules import RulesAdvisor
from .data import GameData
from .log import log
from .match import Snapshot, from_raw
from .sources import Recorder, RecordingSource, RiotSource

# PyInstaller unpacks data files under sys._MEIPASS
PKG = (Path(getattr(sys, "_MEIPASS", "")) / "aram_player") if getattr(sys, "frozen", False) else Path(__file__).parent
STATIC = PKG / "static"
DEMO = PKG / "demo" / "demo.jsonl"

state: dict = {"phase": "Starting"}
lock = threading.Lock()
taken_augments: list[str] = []      # Mayhem augments the player picked this game
current: dict = {}                  # latest snapshot + context, for card comparison
engine: AdviceEngine | None = None


def champ_card(gd: GameData, champ: dict) -> dict:
    return {"id": champ["id"], "name": champ["name"], "icon": gd.champ_icon(champ), "tags": champ.get("tags", [])}


def view(gd: GameData, snap: Snapshot, ctx: Context, advice, ai_status: dict) -> dict:
    """Everything the UI shows, as plain JSON."""
    me = None
    if snap.me:
        me = champ_card(gd, snap.me.champion) | {"build": ctx.build}
        owned = snap.owned
        for it in ctx.build.get("items", []):
            it["owned"] = it["id"] in owned
    return {
        "phase": snap.phase, "mode": snap.mode, "hint": snap.hint, "queue": snap.queue,
        "gameTime": snap.game_time, "me": me,
        "allies": [champ_card(gd, p.champion) for p in snap.allies],
        "bench": [champ_card(gd, c) for c in snap.bench],
        "enemies": [champ_card(gd, p.champion) | {"items": [gd.item_icon(i) for i in p.item_ids]}
                    for p in snap.enemies],
        "advice": advice.to_dict() if advice else None,
        "ai": {"enabled": config.ai_enabled()} | ai_status,
        "taken": list(taken_augments), "recording": config.recording(),
    }


# ----------------------------------------------------------------------------- loop
def run_loop(gd: GameData, demo: bool):
    global engine
    source = RecordingSource(DEMO, delay=8) if demo else RiotSource()
    recorder = Recorder()
    engine = AdviceEngine(gd, RulesAdvisor(gd), ClaudeAdvisor(gd), claude_on=config.ai_enabled)
    mode, last_phase = None, None
    while True:
        delay = 5
        try:
            raw, delay = source.poll()
            if not demo and config.recording():
                recorder.write(raw)
            snap = from_raw(gd, raw, mode)
            mode = snap.mode or mode
            if snap.phase != last_phase:
                log.info("phase -> %s (mode %s, queue %s)", snap.phase, snap.mode, snap.queue)
                if snap.phase == "ChampSelect":
                    taken_augments.clear()          # new game
                last_phase = snap.phase
            ctx = Context(build=gd.metasrc_build(snap.me.champion, snap.mode or "mayhem") if snap.me else {},
                          taken=list(taken_augments))
            advice, ai_status = engine.advise(snap, ctx) if snap.me else (None, {})
            current.update(snap=snap, ctx=ctx)
            with lock:
                state.clear()
                state.update(view(gd, snap, ctx, advice, ai_status))
        except Exception as e:  # never crash the loop
            log.exception("loop error")
            with lock:
                state.clear()
                state.update(phase="Error", hint=f"{e} (details in ~/.aram_player/app.log)")
        time.sleep(delay)


# ----------------------------------------------------------------------------- web
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
API_HEADER = "X-ARAM"          # custom header: browsers won't send it cross-origin without a CORS preflight,
                               # which this server never approves -> blocks CSRF from other websites


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, gd=None, lan_token: str | None = None, **kw):
        self.gd = gd
        self.lan_token = lan_token  # set only with --lan: required for every API call
        super().__init__(*a, directory=str(STATIC), **kw)

    # ------------------------------------------------------------------ access control
    def _host_ok(self) -> bool:
        """Reject DNS-rebinding: a page on evil.com resolving to 127.0.0.1 still sends Host: evil.com."""
        if self.lan_token:
            return True                    # LAN mode: protected by the token instead
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        return host in LOCAL_HOSTS

    def _token_ok(self, query: dict) -> bool:
        if not self.lan_token:
            return True
        given = query.get("token", [""])[0]
        if not given:
            c = SimpleCookie(self.headers.get("Cookie") or "")
            given = c["aram_token"].value if "aram_token" in c else ""
        return hmac.compare_digest(given, self.lan_token)

    def _guard(self, u) -> bool:
        """True if the request may proceed; otherwise a 403 has been sent."""
        q = parse_qs(u.query)
        api = u.path.startswith("/api/")
        if not self._host_ok() or not self._token_ok(q) or (api and self.headers.get(API_HEADER) != "1"):
            self.send_error(403)
            return False
        return True

    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # always serve the latest UI after updates
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if not self._guard(u):
            return
        if self.lan_token and u.path in ("/", "/index.html") and "token=" in u.query:
            # first visit from the phone: remember the token, then drop it from the URL
            self.send_response(302)
            self.send_header("Set-Cookie", f"aram_token={self.lan_token}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Location", "/")
            self.end_headers()
            return
        if u.path == "/api/state":
            with lock:
                return self._json(dict(state))
        if u.path == "/api/ai/refresh":
            if engine:
                engine.reanalyse()
            return self._json({"ok": True})
        if u.path == "/api/build":
            q = parse_qs(u.query)
            champ = self.gd.champ(q.get("champ", [""])[0])
            mode = q.get("mode", ["mayhem"])[0].split()[0]
            return self._json(champ_card(self.gd, champ) | {"build": self.gd.metasrc_build(champ, mode)}
                              if champ else {})
        if u.path == "/api/settings":
            return self._json(config.public())
        if u.path == "/api/augments":
            return self._json(self.gd.augment_catalog())
        return super().do_GET()

    def do_POST(self):
        u = urlparse(self.path)
        if not self._guard(u):
            return
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 64_000)
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
        except ValueError:
            self.send_error(400, "invalid JSON")
            return
        if u.path == "/api/settings":
            upd = {k: body[k] for k in ("ai_enabled", "model", "workspace_id", "record") if k in body}
            if body.get("api_key"):           # empty = keep existing key
                upd["api_key"] = body["api_key"].strip()
            if body.get("clear_key"):
                upd["api_key"] = ""
            config.save(upd)
            return self._json(config.public())
        if u.path == "/api/settings/test":
            try:
                test_key()
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)[:300]})
        if u.path == "/api/augments/rank":
            options = [o.strip() for o in body.get("options", []) if o and o.strip()][:4]
            if not options:
                return self._json({"error": "no options"})
            snap, ctx = current.get("snap"), current.get("ctx")
            if not (engine and snap):
                return self._json({"error": "No game yet"})
            ctx.taken = list(taken_augments)
            return self._json(engine.compare_cards(snap, ctx, options))
        if u.path == "/api/augments/take":
            name = (body.get("name") or "").strip()
            if name and name not in taken_augments and len(taken_augments) < 20:
                taken_augments.append(name)
            return self._json({"taken": taken_augments})
        if u.path == "/api/augments/reset":
            taken_augments.clear()
            return self._json({"taken": taken_augments})
        self.send_error(404)


def start(port: int = 8765, demo: bool = False, lan: bool = False, block: bool = True):
    """Start the background loop + local web server. Used by the CLI and the desktop launcher."""
    print("Loading Data Dragon…", "(AI coach on)" if config.ai_enabled() else "(AI off)")
    gd = GameData()
    print(f"Patch {gd.version}. Open http://127.0.0.1:{port}")
    log.info("patch %s, port %s, ai=%s, model=%s", gd.version, port, config.ai_enabled(), ai_model())
    threading.Thread(target=run_loop, args=(gd, demo), daemon=True).start()
    host = "0.0.0.0" if lan else "127.0.0.1"
    token = secrets.token_urlsafe(12) if lan else None
    if token:
        print(f"LAN mode: open http://<this-computer-ip>:{port}/?token={token} on your phone "
              "(the token changes every start)")
    srv = ThreadingHTTPServer((host, port), lambda *a, **k: Handler(*a, gd=gd, lan_token=token, **k))
    if block:
        srv.serve_forever()
    else:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="fake game, no League client needed")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces (view on phone)")
    ap.add_argument("--no-ai", action="store_true", help="rules + MetaSRC only, no Claude calls")
    args = ap.parse_args()
    if args.no_ai:
        os.environ["ARAM_NO_AI"] = "1"
    start(args.port, args.demo, args.lan)


if __name__ == "__main__":
    main()
