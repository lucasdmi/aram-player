"""Rules advisor: MetaSRC builds + built-in rules. Instant, offline, always available."""
from __future__ import annotations

from ..data import GameData
from ..match import Snapshot
from ..recommender import analyse, final_build, rank_picks
from . import TIER_ORDER, Advice, Context


class RulesAdvisor:
    name = "rules"

    def __init__(self, gd: GameData) -> None:
        self.gd = gd

    def advise(self, snap: Snapshot, ctx: Context) -> Advice:
        a = Advice(source="rules")
        if not snap.me:
            return a
        core = ctx.build.get("items", [])
        a.augment_fits = self._augment_fits(ctx)

        if snap.phase == "ChampSelect":
            options = [snap.me.champion] + snap.bench
            allies = [p.champion for p in snap.allies]
            a.team_fits = [{"name": r["name"], "score": r["score"] / 10, "why": r["why"]}
                           for r in rank_picks(options, allies)]
            if a.team_fits:
                best = max(a.team_fits, key=lambda t: t["score"])
                a.team_note = (f"{best['name']} fits your current team best." if best["name"] != snap.me.name
                               else f"{best['name']} already fits your team well.")
            a.final_build = list(core)
            return a

        enemies = [p.champion for p in snap.enemies]
        an = analyse(self.gd, snap.me.champion, enemies, snap.owned)
        fb = final_build(self.gd, snap.me.champion, core, an["situational"], snap.owned)
        a.summary = an["summary"]
        a.situational = an["situational"]
        a.final_build = fb["final_build"]
        a.reasons = fb["why"] + an["tips"]
        return a

    @staticmethod
    def _augment_fits(ctx: Context) -> dict:
        table = ctx.build.get("augment_table") or []
        out = {}
        for rarity in ("Prismatic", "Gold", "Silver"):
            names = [x["name"] for x in sorted((x for x in table if x["rarity"] == rarity),
                                               key=lambda x: TIER_ORDER.get(x["tier"], 9))][:3]
            if names:
                out[rarity] = names
        return out

    def compare_cards(self, snap: Snapshot, ctx: Context, cards: list[str]) -> list[dict]:
        champ_tier = {x["name"].lower(): x["tier"] for x in (ctx.build.get("augment_table") or [])}
        catalog = {x["name"].lower(): x["rank"] for x in self.gd.augment_catalog()}

        def key(n):
            low = n.lower()
            return TIER_ORDER.get(champ_tier.get(low), 9), catalog.get(low, 9999)

        out = []
        for i, n in enumerate(sorted(cards, key=key)):
            t, rank = key(n)
            why = (f"{champ_tier[n.lower()]} tier for this champion (MetaSRC)" if n.lower() in champ_tier
                   else f"Overall tier-list rank #{rank}" if rank < 9999 else "No data for this card")
            out.append({"name": n, "score": max(1, 9 - i * 3), "why": why})
        return out
