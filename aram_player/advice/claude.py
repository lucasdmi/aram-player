"""Claude advisor: optional, uses the player's own API key. Blocking calls; the AdviceEngine runs
advise() in the background and keeps the rules Advice until this one is ready."""
from __future__ import annotations

import json

from .. import config
from ..data import GameData
from ..match import Snapshot
from . import Advice, Context

MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}


def model() -> str:
    m = config.model_alias()
    return MODELS.get(m, m)


def client():
    import anthropic
    headers = {"anthropic-workspace-id": config.workspace_id()} if config.workspace_id() else {}
    return anthropic.Anthropic(api_key=config.api_key(), default_headers=headers)


TONE = ("Phrase everything as suggestions with reasons ('consider', 'a good option is'), never as orders - "
        "the player makes every decision.")

BUILD_SYSTEM = f"""You are an expert League of Legends ARAM and ARAM Mayhem build coach.
Given my champion, both teams' champions and current items, a baseline build from MetaSRC and a
rule-based threat analysis, suggest a build adapted to THIS enemy team.
- Use ONLY items from the "Valid completed items" list (exactly what can be bought on the ARAM map).
- me.items are ALREADY OWNED. final_build = the complete end inventory of exactly 6 slots, boots
  included, owned items that stay + items still to buy, in buying order.
- Goal: maximum damage while staying alive - for carries usually 4 damage items + boots + 1 defensive
  item against the biggest threat (a 2nd defensive only vs mostly divers/assassins).
- Only Grievous Wounds items cut healing (Mortal Reminder, Executioner's Calling, Chempunk Chainsword,
  Morellonomicon, Oblivion Orb, Thornmail, Bramble Vest). If rules_analysis lists healers, include one
  suited to my champion unless you explain why not.
- Only call a champion a healer/tank if that is their kit. Lord Dominik's/Serylda's are for tanky enemies.
- Tailor everything to MY champion's kit, win condition and damage type; defensive items must be ones
  my class buys. Reasons must not contradict each other. Start "playstyle" with my champion's name.
- For Mayhem, augment_picks = best 3 per rarity from augment_options for THIS enemy team.
{TONE}"""

PICKS_SYSTEM = f"""You are an ARAM / ARAM Mayhem draft expert. The enemy team is unknown. Score the
player's options (current champion + bench) 1-10 by strength in this mode AND fit with the allied
team (frontline, engage, AP/AD balance, sustain, waveclear/poke). 'why' max 15 words.
'note': one sentence on the trade-offs between the options, as information. {TONE}"""

CARDS_SYSTEM = f"""You are an ARAM Mayhem expert. The player is offered augment cards. Score each 1-10
for THEIR champion, current items and THIS enemy team (threats, CC, healing, tanks), considering synergy
with augments already taken. 'why' max 15 words, phrased as a reason. {TONE}"""


def _tool_call(system: str, tool: dict, content: str, max_tokens: int) -> dict:
    msg = client().messages.create(model=model(), max_tokens=max_tokens, system=system, tools=[tool],
                                   tool_choice={"type": "tool", "name": tool["name"]},
                                   messages=[{"role": "user", "content": content}])
    for b in msg.content:
        if getattr(b, "type", "") == "tool_use":
            return dict(b.input)
    raise ValueError(f"no tool output (stop_reason={msg.stop_reason})")


_RANKING = {"type": "array", "items": {"type": "object", "properties": {
    "name": {"type": "string"}, "score": {"type": "integer", "minimum": 1, "maximum": 10},
    "why": {"type": "string"}}, "required": ["name", "score", "why"]}}


class ClaudeAdvisor:
    name = "claude"

    def __init__(self, gd: GameData) -> None:
        self.gd = gd
        self._valid_items: list[str] | None = None

    # ----------------------------------------------------------------- helpers
    def _names(self, ids) -> list[str]:
        return [self.gd.items[i]["name"] for i in ids if i in self.gd.items]

    def _valid(self) -> list[str]:
        if self._valid_items is None:
            self._valid_items = sorted({self.gd.items[i]["name"] for i in self.gd.aram_ids
                                        if self.gd.is_completed_item(i) or self.gd.is_boots(i)})
        return self._valid_items

    def _game_payload(self, snap: Snapshot, ctx: Context) -> dict:
        from ..recommender import analyse
        an = analyse(self.gd, snap.me.champion, [p.champion for p in snap.enemies], snap.owned)
        table = ctx.build.get("augment_table") or []
        payload = {
            "mode": snap.mode, "game_time_s": round(snap.game_time),
            "me": {"champion": snap.me.name, "tags": snap.me.champion.get("tags"),
                   "items": self._names(snap.me.item_ids)},
            "allies": [{"champion": p.name, "items": self._names(p.item_ids), "level": p.level} for p in snap.allies],
            "enemies": [{"champion": p.name, "tags": p.champion.get("tags"), "items": self._names(p.item_ids),
                         "level": p.level, "kda": p.kda} for p in snap.enemies],
            "metasrc_baseline": [i["name"] for i in ctx.build.get("items", [])],
            "rules_analysis": an["summary"] | {"suggested_situational": [i["name"] for i in an["situational"]]},
            "augments_taken": ctx.taken,
        }
        if table:
            payload["augment_options"] = {r: [f'{a["name"]} ({a["tier"]})' for a in table if a["rarity"] == r][:20]
                                          for r in ("Prismatic", "Gold", "Silver")}
        return payload

    # ----------------------------------------------------------------- Advisor
    def advise(self, snap: Snapshot, ctx: Context) -> Advice:
        if snap.phase == "ChampSelect":
            payload = {"mode": snap.mode, "current": snap.me.name,
                       "options": [snap.me.name] + [c["name"] for c in snap.bench],
                       "allies": [p.name for p in snap.allies]}
            tool = {"name": "score_options", "description": "Score each champion option.",
                    "input_schema": {"type": "object", "properties": {"ranking": _RANKING, "note": {"type": "string"}},
                                     "required": ["ranking", "note"]}}
            res = _tool_call(PICKS_SYSTEM, tool, json.dumps(payload, indent=1), 700)
            return Advice(source="claude", team_fits=res.get("ranking", []), team_note=res.get("note", ""))

        tool = {"name": "submit_build", "description": "Return the suggested build.",
                "input_schema": {"type": "object", "properties": {
                    "final_build": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                    "augment_picks": {"type": "object", "properties": {
                        r: {"type": "array", "items": {"type": "string"}} for r in ("Prismatic", "Gold", "Silver")}},
                    "playstyle": {"type": "string"},
                    "reasons": {"type": "array", "items": {"type": "string"}}},
                    "required": ["final_build", "playstyle", "reasons"]}}
        content = ("Game state:\n" + json.dumps(self._game_payload(snap, ctx), indent=1)
                   + "\n\nValid completed items this patch:\n" + ", ".join(self._valid()))
        res = _tool_call(BUILD_SYSTEM, tool, content, 1000)
        return Advice(source="claude", final_build=res.get("final_build", []),
                      augment_fits=res.get("augment_picks") or {}, playstyle=res.get("playstyle", ""),
                      reasons=res.get("reasons", []))

    def compare_cards(self, snap: Snapshot, ctx: Context, cards: list[str]) -> list[dict]:
        tool = {"name": "score_cards", "description": "Score each offered card.",
                "input_schema": {"type": "object", "properties": {"ranking": _RANKING}, "required": ["ranking"]}}
        payload = self._game_payload(snap, ctx) if snap.me and snap.phase == "InGame" else {"mode": snap.mode}
        res = _tool_call(CARDS_SYSTEM, tool, "Game:\n" + json.dumps(payload, indent=1)
                         + "\n\nOffered cards: " + json.dumps(cards), 600)
        return res.get("ranking", [])


def test_key() -> None:
    """Raises if the configured key/model doesn't work."""
    client().messages.create(model=model(), max_tokens=5, messages=[{"role": "user", "content": "ping"}])
