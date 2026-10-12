"""Game source: where raw game data comes from (see CONTEXT.md).

Adapters:
  RiotSource       – League client API + in-game Live Client Data API (read-only).
  RecordingSource  – replays a recording (.jsonl, one raw tick per line); powers the demo and tests.
Recorder           – optionally saves raw ticks, other players anonymized, last 10 games kept.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from . import live_client
from .lcu import LCU
from .match import IN_GAME_PHASES

RECORDINGS = Path.home() / ".aram_player" / "recordings"
KEEP_GAMES = 10


class RiotSource:
    """One poll = one raw tick; fetches only what the current phase needs."""

    def __init__(self) -> None:
        self.lcu = LCU()

    def poll(self) -> tuple[dict, float]:
        phase = self.lcu.phase()
        raw = {"t": time.time(), "phase": phase, "gameflow": None, "champ_select": None, "live": None}
        if phase == "ChampSelect":
            raw["gameflow"] = self.lcu.gameflow_session()
            raw["champ_select"] = self.lcu.champ_select()
        elif phase in IN_GAME_PHASES:
            raw["gameflow"] = self.lcu.gameflow_session()
            raw["live"] = live_client.all_game_data()
        delay = {"ChampSelect": 2, "InProgress": 3, "GameStart": 3}.get(phase, 5) if phase else 10
        return raw, delay


class RecordingSource:
    """Replays raw ticks from a .jsonl recording, looping forever (demo) or once (tests)."""

    def __init__(self, path: Path | str, loop: bool = True, delay: float = 3.0) -> None:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        self.ticks = [json.loads(l) for l in lines if l.strip()]
        self.loop, self.delay, self.i = loop, delay, 0

    def poll(self) -> tuple[dict, float]:
        if self.i >= len(self.ticks):
            if not self.loop:
                return {"phase": "EndOfGame"}, self.delay
            self.i = 0
        tick = self.ticks[self.i]
        self.i += 1
        return tick, self.delay


# --------------------------------------------------------------------------- recording
_PRIVATE_KEYS = {"summonerId", "puuid", "obfuscatedPuuid", "obfuscatedSummonerId", "gameName", "tagLine",
                 "summonerName", "riotId", "riotIdGameName", "riotIdTagLine", "playerId", "accountId"}


def anonymize(raw: dict) -> dict:
    """Copy of a raw tick with every player identity replaced by 'Player N' (stable within the tick)."""
    raw = copy.deepcopy(raw)
    names: dict[str, str] = {}

    def alias(v):
        if v in (None, "", 0):
            return v
        return names.setdefault(str(v), f"Player {len(names) + 1}")

    def walk(o):
        if isinstance(o, dict):
            for k, v in list(o.items()):
                if k in _PRIVATE_KEYS and not isinstance(v, (dict, list)):
                    o[k] = alias(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    live = raw.get("live") or {}
    me = (live.get("activePlayer") or {}).get("riotId")
    if me:
        alias(me)  # the player themself is always "Player 1"
    walk(raw)
    return raw


def _fingerprint(raw: dict) -> str:
    """What matters for advice; ticks with the same fingerprint are not saved again."""
    live = raw.get("live") or {}
    players = [(p.get("championName"), sorted(i.get("itemID", 0) for i in p.get("items", [])))
               for p in live.get("allPlayers", [])]
    cs = raw.get("champ_select") or {}
    team = [(p.get("cellId"), p.get("championId")) for p in cs.get("myTeam", [])]
    bench = [b.get("championId") for b in cs.get("benchChampions", [])] or cs.get("benchChampionIds", [])
    return json.dumps([raw.get("phase"), players, team, bench], sort_keys=True)


class Recorder:
    """Saves raw ticks of ChampSelect and in-game phases, one file per game."""

    def __init__(self, folder: Path = RECORDINGS) -> None:
        self.folder, self.file, self.last_fp, self.last_phase = folder, None, None, None

    def write(self, raw: dict) -> None:
        phase = raw.get("phase")
        if phase not in IN_GAME_PHASES and phase != "ChampSelect":
            self.last_phase = phase
            return
        if self.file is None or (phase == "ChampSelect" and self.last_phase not in (None, "ChampSelect")):
            self._new_file()
        self.last_phase = phase
        fp = _fingerprint(raw)
        if fp == self.last_fp:
            return
        self.last_fp = fp
        with self.file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(anonymize(raw)) + "\n")

    def _new_file(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.file = self.folder / time.strftime("game-%Y%m%d-%H%M%S.jsonl")
        self.last_fp = None
        for old in sorted(self.folder.glob("game-*.jsonl"))[:-(KEEP_GAMES - 1)]:
            try:
                old.unlink()
            except OSError:
                pass
