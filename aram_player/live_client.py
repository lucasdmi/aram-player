"""Riot's official in-game Live Client Data API (https://127.0.0.1:2999).

This is a public, read-only endpoint Riot provides for third-party apps.
It only exposes what the scoreboard (Tab) already shows you.
"""
from __future__ import annotations

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"


def all_game_data() -> dict | None:
    try:
        r = requests.get(URL, verify=False, timeout=1.5)
        return r.json() if r.status_code == 200 else None
    except requests.RequestException:
        return None


def split_teams(data: dict) -> tuple[dict | None, list[dict], list[dict]]:
    """Return (me, allies, enemies) from allgamedata."""
    active = data.get("activePlayer", {})
    my_ids = {active.get("riotId"), active.get("summonerName")} - {None, ""}
    players = data.get("allPlayers", [])
    me = next(
        (p for p in players if p.get("riotId") in my_ids or p.get("summonerName") in my_ids),
        None,
    )
    if not me:
        return None, [], []
    team = me.get("team")
    allies = [p for p in players if p.get("team") == team and p is not me]
    enemies = [p for p in players if p.get("team") != team]
    return me, allies, enemies
