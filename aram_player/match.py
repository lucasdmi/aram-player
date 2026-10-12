"""Match snapshot: everything the app knows about the current game at one moment.

One shape for every phase (see CONTEXT.md). Built ONLY from a raw tick produced by a Game source,
so live play and recordings go through exactly the same parsing.

Raw tick (dict):
    {"t": unix time, "phase": str | None, "gameflow": dict | None,
     "champ_select": dict | None, "live": dict | None}
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .data import GameData

ARAM_MAP_ID = 12
MAYHEM_QUEUES = {2400}          # ARAM: Mayhem
MAYHEM_GAMEMODES = {"KIWI"}     # internal game mode name for ARAM: Mayhem
IN_GAME_PHASES = {"InProgress", "GameStart"}


@dataclass
class Player:
    champion: dict                      # Data Dragon champion record
    item_ids: list[str] = field(default_factory=list)
    level: int = 0
    kda: str = ""

    @property
    def name(self) -> str:
        return self.champion["name"]


@dataclass
class Snapshot:
    phase: str                          # "Client not running", "Lobby", "ChampSelect", "InGame", "Loading", …
    mode: str | None = None             # "aram" | "mayhem" | None
    me: Player | None = None
    allies: list[Player] = field(default_factory=list)
    bench: list[dict] = field(default_factory=list)      # champion records, champ select only
    enemies: list[Player] = field(default_factory=list)  # in game only
    game_time: float = 0.0
    queue: dict = field(default_factory=dict)            # raw queue info, for debugging
    hint: str = ""

    @property
    def owned(self) -> set[str]:
        return set(self.me.item_ids) if self.me else set()


def detect_mode(gameflow: dict | None, live_game_mode: str | None = None) -> str | None:
    """'mayhem', 'aram' or None (not an ARAM game)."""
    q = (gameflow or {}).get("gameData", {}).get("queue", {})
    text = " ".join(str(q.get(k, "")) for k in ("description", "detailedDescription", "name", "gameMode")).lower()
    if (q.get("id") in MAYHEM_QUEUES or q.get("gameMode") in MAYHEM_GAMEMODES
            or live_game_mode in MAYHEM_GAMEMODES or "mayhem" in text or "augment" in text):
        return "mayhem"
    if q.get("mapId") == ARAM_MAP_ID or q.get("id") == 450 or "aram" in text or live_game_mode == "ARAM":
        return "aram"
    return None


def from_raw(gd: GameData, raw: dict, last_mode: str | None = None) -> Snapshot:
    phase = raw.get("phase")
    gameflow = raw.get("gameflow")
    live = raw.get("live")
    q = (gameflow or {}).get("gameData", {}).get("queue", {})
    queue = {k: q.get(k) for k in ("id", "gameMode", "name", "mapId")}
    live_mode = (live or {}).get("gameData", {}).get("gameMode")
    if live_mode:
        queue["live_game_mode"] = live_mode
    mode = detect_mode(gameflow, live_mode) or last_mode

    if phase is None:
        return Snapshot("Client not running", hint="Open the League client.")
    if phase == "ChampSelect":
        return _champ_select(gd, raw.get("champ_select") or {}, mode, queue)
    if phase in IN_GAME_PHASES:
        if not live:
            return Snapshot("Loading", mode, queue=queue, hint="Waiting for the game to load…")
        return _in_game(gd, live, mode, queue)
    return Snapshot(phase, mode, queue=queue, hint="Waiting for an ARAM champ select…")


def _champ_select(gd: GameData, cs: dict, mode, queue) -> Snapshot:
    me_cell = cs.get("localPlayerCellId")
    team = cs.get("myTeam", [])
    me_raw = next((p for p in team if p.get("cellId") == me_cell), {})
    my_champ = gd.champ(me_raw.get("championId") or 0)
    bench_ids = [b.get("championId") for b in cs.get("benchChampions", [])] or cs.get("benchChampionIds", [])
    bench = [c for c in (gd.champ(i) for i in bench_ids) if c and c is not my_champ]
    allies = [Player(c) for c in (gd.champ(p.get("championId") or 0)
                                  for p in team if p.get("cellId") != me_cell) if c]
    return Snapshot("ChampSelect", mode, me=Player(my_champ) if my_champ else None, allies=allies,
                    bench=bench, queue=queue,
                    hint="Enemy team is hidden in ARAM champ select; counters appear once the game loads.")


def _player(gd: GameData, p: dict) -> Player | None:
    c = gd.champ(p.get("championName", "")) or gd.champ(p.get("rawChampionName", "").split("_")[-1])
    if not c:
        return None
    sc = p.get("scores", {})
    return Player(c, [str(i["itemID"]) for i in p.get("items", [])], p.get("level", 0),
                  f'{sc.get("kills", 0)}/{sc.get("deaths", 0)}/{sc.get("assists", 0)}')


def _in_game(gd: GameData, live: dict, mode, queue) -> Snapshot:
    active = live.get("activePlayer", {})
    my_ids = {active.get("riotId"), active.get("summonerName")} - {None, ""}
    players = live.get("allPlayers", [])
    me_raw = next((p for p in players if p.get("riotId") in my_ids or p.get("summonerName") in my_ids), None)
    game_time = live.get("gameData", {}).get("gameTime", 0)
    if not me_raw:
        return Snapshot("InGame", mode, queue=queue, game_time=game_time,
                        hint="Could not identify your player yet.")
    team = me_raw.get("team")
    allies = [x for x in (_player(gd, p) for p in players if p is not me_raw and p.get("team") == team) if x]
    enemies = [x for x in (_player(gd, p) for p in players if p.get("team") != team) if x]
    return Snapshot("InGame", mode, me=_player(gd, me_raw), allies=allies, enemies=enemies,
                    game_time=game_time, queue=queue)
