"""Offline tests: no League client, no internet, no API key needed.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aram_player.advice import Advice, AdviceEngine, Context, guard
from aram_player.advice.rules import RulesAdvisor
from aram_player.data import GameData
from aram_player.match import Player, Snapshot, detect_mode, from_raw
from aram_player.sources import Recorder, RecordingSource, anonymize

HERE = Path(__file__).parent
DEMO = HERE.parent / "aram_player" / "demo" / "demo.jsonl"


def game_data() -> GameData:
    d = json.loads((HERE / "fixtures" / "ddragon_min.json").read_text())
    gd = GameData.from_data(d["version"], d["champions"], d["items"])
    gd.augment_catalog = lambda: []       # no network in tests
    return gd


GD = game_data()
CORE = [GD.item_ref_by_id(i) for i in ("3006", "6676", "3031", "3036", "3072", "3085")]
CTX = Context(build={"items": CORE, "augment_table": [
    {"name": "Dual Wield", "rarity": "Prismatic", "tier": "S+", "icon": ""},
    {"name": "Soul Siphon", "rarity": "Gold", "tier": "S+", "icon": ""},
    {"name": "Blunt Force", "rarity": "Silver", "tier": "S", "icon": ""},
    {"name": "Typhoon", "rarity": "Silver", "tier": "C", "icon": ""}]})


def in_game(me: str, enemies: list[str], owned=()) -> Snapshot:
    return Snapshot("InGame", "mayhem", me=Player(GD.champ(me), list(owned)),
                    enemies=[Player(GD.champ(e)) for e in enemies])


DRAVEN_GAME = ["Hwei", "Yone", "Twitch", "Jinx", "Darius"]
SERAPHINE_GAME = ["Darius", "Draven", "Soraka", "Zed", "Talon"]


class MatchSnapshotTests(unittest.TestCase):
    def test_demo_recording_replays_champ_select_then_game(self):
        src = RecordingSource(DEMO, loop=False)
        cs = from_raw(GD, src.poll()[0])
        self.assertEqual(cs.phase, "ChampSelect")
        self.assertEqual(cs.mode, "mayhem")
        self.assertEqual(cs.me.name, "Draven")
        self.assertEqual([c["name"] for c in cs.bench], ["Malphite", "Darius", "Annie"])
        self.assertEqual(len(cs.allies), 4)
        game = from_raw(GD, src.poll()[0])
        self.assertEqual(game.phase, "InGame")
        self.assertEqual([p.name for p in game.enemies], DRAVEN_GAME)
        self.assertEqual(game.owned, {"3006", "6676"})
        self.assertEqual(from_raw(GD, src.poll()[0]).phase, "EndOfGame")

    def test_mode_detection(self):
        q = lambda **k: {"gameData": {"queue": k}}
        self.assertEqual(detect_mode(q(id=2400, mapId=12)), "mayhem")
        self.assertEqual(detect_mode(q(name="ARAM: Desordem", gameMode="KIWI", mapId=12)), "mayhem")  # Portuguese
        self.assertEqual(detect_mode(q(id=450, mapId=12)), "aram")
        self.assertEqual(detect_mode(None, "KIWI"), "mayhem")
        self.assertIsNone(detect_mode(q(id=420, mapId=11)))

    def test_client_closed_and_loading(self):
        self.assertEqual(from_raw(GD, {"phase": None}).phase, "Client not running")
        self.assertEqual(from_raw(GD, {"phase": "InProgress", "live": None}).phase, "Loading")


class AdviceGuardTests(unittest.TestCase):
    def assertSane(self, snap: Snapshot, advice: Advice):
        ids = [i["id"] for i in advice.final_build]
        self.assertLessEqual(len(ids), 6, "more than 6 slots")
        self.assertEqual(len(ids), len(set(ids)), "duplicate item")
        self.assertLessEqual(sum(GD.is_boots(i) for i in ids), 1, "two pairs of boots")
        self.assertNotIn(advice.next_item, [GD.items[i]["name"] for i in snap.owned], "suggests owned item")
        for i in ids:
            if i not in snap.owned:
                self.assertTrue(GD.is_aram_buyable(i), f"{GD.items[i]['name']} not buyable in ARAM")
                dt = GD.damage_type(i)
                self.assertFalse(advice.role == "ap" and dt == "ad", f"AD item {i} for AP champion")
                self.assertFalse(advice.role == "ad" and dt == "ap", f"AP item {i} for AD champion")
        for s in advice.situational:
            self.assertNotIn(s["id"], snap.owned)

    def test_rules_draven(self):
        snap = in_game("Draven", DRAVEN_GAME, owned=["3006", "6676"])
        a = guard(GD, snap, RulesAdvisor(GD).advise(snap, CTX), CTX)
        self.assertSane(snap, a)
        self.assertEqual(len(a.final_build), 6)
        self.assertEqual(a.next_item, "Infinity Edge")
        self.assertIn("Mortal Reminder", [i["name"] for i in a.final_build])   # Yone + Darius heal

    def test_rules_seraphine_gets_no_ad_items(self):            # regression: AD items for Seraphine
        snap = in_game("Seraphine", SERAPHINE_GAME)
        a = guard(GD, snap, RulesAdvisor(GD).advise(snap, CTX), CTX)
        self.assertEqual(a.role, "ap")
        self.assertSane(snap, a)
        self.assertIn("Morellonomicon", [s["name"] for s in a.situational])

    def test_guard_cleans_a_bad_claude_answer(self):            # regressions: 7 items, owned, Guardian Angel
        snap = in_game("Draven", DRAVEN_GAME, owned=["3006", "6676"])
        bad = Advice(source="claude", final_build=[
            "The Collector", "Berserker's Greaves", "Mercury's Treads", "Guardian Angel", "Zhonya's Hourglass",
            "Infinity Edge", "Mortal Reminder", "Bloodthirster", "Death's Dance", "Made Up Item"],
            augment_fits={"Prismatic": ["Dual Wield (S+)", "Not An Augment"]})
        a = guard(GD, snap, bad, CTX)
        names = [i["name"] for i in a.final_build]
        self.assertSane(snap, a)
        self.assertEqual(names, ["Berserker's Greaves", "The Collector", "Infinity Edge", "Mortal Reminder",
                                 "Bloodthirster", "Death's Dance"])
        self.assertEqual(a.next_item, "Infinity Edge")
        self.assertEqual(a.augment_fits, {"Prismatic": ["Dual Wield"]})

    def test_build_complete(self):
        owned = ["3006", "6676", "3031", "3036", "3072", "3033"]
        snap = in_game("Draven", DRAVEN_GAME, owned=owned)
        a = guard(GD, snap, RulesAdvisor(GD).advise(snap, CTX), CTX)
        self.assertEqual(a.next_item, "Build complete")
        self.assertEqual({i["id"] for i in a.final_build}, set(owned))


class TeamFitTests(unittest.TestCase):
    def test_squishy_team_prefers_frontline(self):
        snap = Snapshot("ChampSelect", "mayhem", me=Player(GD.champ("Draven")),
                        allies=[Player(GD.champ(n)) for n in ("Lux", "Xerath", "Ezreal", "Ziggs")],
                        bench=[GD.champ(n) for n in ("Malphite", "Darius", "Annie")])
        a = guard(GD, snap, RulesAdvisor(GD).advise(snap, CTX), CTX)
        order = [t["name"] for t in a.team_fits]
        self.assertEqual(set(order[:2]), {"Malphite", "Darius"})   # the frontliners lead
        self.assertEqual(order[-1], "Annie")                       # a 4th AP is the worst fit
        self.assertTrue(all(1 <= t["score"] <= 10 for t in a.team_fits))
        self.assertNotIn("Swap", a.team_note)                    # options, not orders


class FakeClaude:
    name = "claude"

    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def advise(self, snap, ctx):
        self.calls += 1
        if self.fail:
            raise RuntimeError("401 invalid key")
        return Advice(source="claude", final_build=["Infinity Edge", "Guardian Angel", "Death's Dance"],
                      playstyle="Draven: consider staying behind your frontline.")

    def compare_cards(self, snap, ctx, cards):
        if self.fail:
            raise RuntimeError("timeout")
        return [{"name": c, "score": 12 - i, "why": "x"} for i, c in enumerate(cards)]


class EngineTests(unittest.TestCase):
    def wait(self, engine):
        import time
        for _ in range(100):
            if engine.status["state"] != "running":
                return
            time.sleep(0.01)

    def test_rules_first_then_claude_upgrades(self):
        claude = FakeClaude()
        eng = AdviceEngine(GD, RulesAdvisor(GD), claude, claude_on=lambda: True)
        snap = in_game("Draven", DRAVEN_GAME, owned=["3006", "6676"])
        first, status = eng.advise(snap, CTX)
        self.assertEqual(first.source, "rules")                  # never blocks on Claude
        self.wait(eng)
        second, _ = eng.advise(snap, CTX)
        self.assertEqual(second.source, "claude")
        self.assertNotIn("Guardian Angel", [i["name"] for i in second.final_build])  # guard still applies
        eng.advise(snap, CTX)
        self.assertEqual(claude.calls, 1)                        # no re-think without a real change
        snap.enemies[0].item_ids.append("3157")                  # an enemy completes an item
        eng.advise(snap, CTX); self.wait(eng)
        self.assertEqual(claude.calls, 2)

    def test_claude_error_keeps_rules(self):
        eng = AdviceEngine(GD, RulesAdvisor(GD), FakeClaude(fail=True), claude_on=lambda: True)
        snap = in_game("Draven", DRAVEN_GAME)
        eng.advise(snap, CTX); self.wait(eng)
        a, status = eng.advise(snap, CTX)
        self.assertEqual(a.source, "rules")
        self.assertEqual(status["state"], "error")
        self.assertTrue(a.final_build)

    def test_card_comparison_fallback_and_clamp(self):
        snap = in_game("Draven", DRAVEN_GAME)
        ok = AdviceEngine(GD, RulesAdvisor(GD), FakeClaude(), claude_on=lambda: True)
        r = ok.compare_cards(snap, CTX, ["Typhoon", "Dual Wield"])
        self.assertEqual(r["source"], "claude")
        self.assertTrue(all(1 <= x["score"] <= 10 for x in r["ranking"]))
        bad = AdviceEngine(GD, RulesAdvisor(GD), FakeClaude(fail=True), claude_on=lambda: True)
        r = bad.compare_cards(snap, CTX, ["Typhoon", "Dual Wield"])
        self.assertEqual(r["source"], "rules")
        self.assertEqual(r["ranking"][0]["name"], "Dual Wield")  # S+ beats C for this champion


class RecordingTests(unittest.TestCase):
    def test_anonymize_and_keep_last_ten(self):
        tick = json.loads(DEMO.read_text().splitlines()[1])
        anon = anonymize(tick)
        ids = [p["riotId"] for p in anon["live"]["allPlayers"]]
        self.assertEqual(anon["live"]["activePlayer"]["riotId"], "Player 1")
        self.assertEqual(ids[0], "Player 1")
        self.assertTrue(all(i.startswith("Player ") for i in ids))
        self.assertEqual(from_raw(GD, anon).me.name, "Draven")   # still parses after anonymizing
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            for n in range(12):
                (folder / f"game-2026010{n:02d}.jsonl").write_text("{}\n")
            rec = Recorder(folder)
            rec.write({"phase": "ChampSelect", "champ_select": {"myTeam": [{"cellId": n}]}})
            self.assertEqual(len(list(folder.glob("game-*.jsonl"))), 10)


class MetaSrcParserTest(unittest.TestCase):
    HTML = """<html><body>
      <img alt="Core Item: Kraken" src="/lol/img/items/kraken-6676.png">
      <img alt="Berserker's Greaves" src="/lol/img/items/berserkers-greaves-3006.png">
      <img alt="Collector" src="/lol/img/items/collector-6676.png">
      <img alt="Infinity Edge" data-src="/lol/img/items/infinity-edge-3031.png">
      <img alt="Flash" src="/lol/img/spells/flash.png">
      <img alt="Mark" src="/lol/img/spells/mark.png">
      <img alt="Quest: Steel Your Heart" src="/lol/img/augments/quest/steel.png">
      <script id="ArenaWidget_row_data" type="application/json">
        [{"values": {"name": "Tank Engine", "rarity": 2, "tier": "A"}},
         {"values": {"name": "Ultimate Unstoppable", "rarity": 3, "tier": "S"}}]
      </script></body></html>"""

    def test_parse_returns_every_section(self):
        out = GD._parse_metasrc(self.HTML)
        ids = [i["id"] for i in out["items"]]
        self.assertIn("3006", ids)                       # boots kept
        self.assertIn("3031", ids)
        self.assertEqual(out["spells"], ["Flash", "Mark"])
        self.assertEqual([a["name"] for a in out["augments"]], ["Quest: Steel Your Heart"])
        self.assertEqual(out["augment_table"][0], {"name": "Ultimate Unstoppable", "rarity": "Prismatic",
                                                   "tier": "S", "icon": None})


class WebSecurityTest(unittest.TestCase):
    """CSRF / DNS-rebinding / LAN-token checks on the local web server."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer
        from aram_player import main as core
        cls.servers = {}
        for name, token in (("local", None), ("lan", "s3cret")):
            srv = ThreadingHTTPServer(("127.0.0.1", 0),
                                      lambda *a, t=token, **k: core.Handler(*a, gd=GD, lan_token=t, **k))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            cls.servers[name] = srv

    @classmethod
    def tearDownClass(cls):
        for srv in cls.servers.values():
            srv.shutdown()

    def status(self, server, path, headers=None, method="GET", body=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.servers[server].server_address[1], timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        code = conn.getresponse().status
        conn.close()
        return code

    def test_local(self):
        self.assertEqual(self.status("local", "/api/state", {"X-ARAM": "1"}), 200)
        self.assertEqual(self.status("local", "/api/state"), 403)                       # no custom header
        self.assertEqual(self.status("local", "/api/state", {"X-ARAM": "1", "Host": "evil.com"}), 403)
        self.assertEqual(self.status("local", "/api/augments/take", {"X-ARAM": "1"}, "POST", "not json"), 400)

    def test_lan_needs_token(self):
        self.assertEqual(self.status("lan", "/api/state", {"X-ARAM": "1"}), 403)
        self.assertEqual(self.status("lan", "/api/state", {"X-ARAM": "1", "Cookie": "aram_token=nope"}), 403)
        self.assertEqual(self.status("lan", "/api/state", {"X-ARAM": "1", "Cookie": "aram_token=s3cret"}), 200)
        self.assertEqual(self.status("lan", "/?token=s3cret"), 302)


if __name__ == "__main__":
    unittest.main()
