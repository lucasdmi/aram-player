"""Advice: the Advisor interface, the Advice guard and "rules first, Claude upgrades" (see CONTEXT.md).

Callers only need:
    engine = AdviceEngine(gd, RulesAdvisor(gd), ClaudeAdvisor(gd))
    advice, status = engine.advise(snapshot, ctx)          # never blocks on Claude
    result = engine.compare_cards(snapshot, ctx, ["A", "B", "C"])
"""
from __future__ import annotations

import re
import threading
from dataclasses import asdict, dataclass, field
from typing import Protocol

from ..data import GameData
from ..log import log
from ..match import Snapshot
from ..recommender import my_role

TIER_ORDER = {"S+": 0, "S": 1, "A": 2, "B": 3, "C": 4, "D": 5}


@dataclass
class Context:
    """What advisors may use besides the snapshot."""
    build: dict = field(default_factory=dict)       # MetaSRC: items, augments, augment_table, spells, error?
    taken: list[str] = field(default_factory=list)  # Mayhem augments the player picked this game


@dataclass
class Advice:
    source: str = "rules"                                 # "rules" | "claude"
    team_fits: list[dict] = field(default_factory=list)   # champ select: [{name, score 1-10, why}], best first
    team_note: str = ""
    final_build: list[dict] = field(default_factory=list) # ≤ 6 item refs {id, name, icon, owned}
    next_item: str = ""
    situational: list[dict] = field(default_factory=list) # [{id, name, icon, why, owned}]
    augment_fits: dict[str, list[str]] = field(default_factory=dict)  # rarity -> names
    playstyle: str = ""
    reasons: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)           # enemy threat summary
    role: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class Advisor(Protocol):
    name: str

    def advise(self, snap: Snapshot, ctx: Context) -> Advice: ...

    def compare_cards(self, snap: Snapshot, ctx: Context, cards: list[str]) -> list[dict]: ...


# --------------------------------------------------------------------------- the guard
def _clean_name(n: str) -> str:
    return re.sub(r"\s*\(.*\)$", "", str(n)).strip()


def guard(gd: GameData, snap: Snapshot, advice: Advice, ctx: Context | None = None) -> Advice:
    """The single post-processing step every Advice passes (CONTEXT.md: Advice guard)."""
    owned = snap.owned
    role = my_role(gd, snap.me.champion, owned) if snap.me else ""
    advice.role = role

    def ok(ref: dict) -> bool:
        iid = ref["id"]
        if iid in owned:
            return True
        if not gd.is_aram_buyable(iid):
            return False
        dt = gd.damage_type(iid)
        return not ((role == "ad" and dt == "ap") or (role == "ap" and dt == "ad"))

    def ref_of(x) -> dict | None:
        if isinstance(x, dict) and x.get("id"):
            return gd.item_ref_by_id(x["id"])
        return gd.item_ref(_clean_name(x)) if isinstance(x, str) else None

    # final build: owned completed items + boots first, then suggestions; max one boots; ≤ 6
    owned_core = [gd.item_ref_by_id(i) for i in snap.me.item_ids if (gd.is_completed_item(i) or gd.is_boots(i))] \
        if snap.me else []
    final, seen, has_boots = [], set(), False
    for ref in owned_core + [ref_of(x) for x in advice.final_build]:
        if not ref or ref["id"] in seen or not ok(ref):
            continue
        if gd.is_boots(ref["id"]):
            if has_boots:
                continue
            has_boots = True
        seen.add(ref["id"])
        final.append({**ref, "owned": ref["id"] in owned})
        if len(final) == 6:
            break
    advice.final_build = final
    to_buy = [i for i in final if not i["owned"]]
    advice.next_item = to_buy[0]["name"] if to_buy else ("Build complete" if final else "")

    sit = []
    for s in advice.situational:
        ref = ref_of(s)
        if ref and ref["id"] not in owned and ok(ref) and all(x["id"] != ref["id"] for x in sit):
            sit.append({**ref, "why": s.get("why", "") if isinstance(s, dict) else "", "owned": False})
    advice.situational = sit

    table = {a["name"].lower(): a["name"] for a in (ctx.build.get("augment_table") or [])} if ctx else {}
    fits = {}
    for rarity, names in (advice.augment_fits or {}).items():
        clean = [_clean_name(n) for n in names]
        if table:
            clean = [table[n.lower()] for n in clean if n.lower() in table]
        if clean:
            fits[rarity] = list(dict.fromkeys(clean))[:3]
    advice.augment_fits = fits

    for t in advice.team_fits:
        t["score"] = max(1, min(10, int(float(t.get("score", 5)) + 0.5)))   # round half up
        if isinstance(t.get("why"), list):
            t["why"] = "; ".join(t["why"])
    advice.team_fits.sort(key=lambda t: -t["score"])
    return advice


# --------------------------------------------------------------------------- engine
def rethink_key(snap: Snapshot, force: int) -> tuple:
    """A real change: enemy team, completed items of any player, champ-select options, or Re-analyse."""
    def completed(p):
        return tuple(sorted(p.item_ids))
    if snap.phase == "ChampSelect":
        return ("cs", snap.me.name if snap.me else None, tuple(sorted(c["name"] for c in snap.bench)),
                tuple(sorted(p.name for p in snap.allies)), force)
    return ("game", snap.me.name if snap.me else None, tuple(sorted(p.name for p in snap.enemies)),
            tuple(completed(p) for p in [snap.me, *snap.allies, *snap.enemies] if p), force)


class AdviceEngine:
    """Rules first, Claude upgrades: rules answer now; Claude's answer replaces it when ready."""

    UPGRADE_FIELDS = ("team_fits", "team_note", "final_build", "augment_fits", "playstyle", "reasons")

    def __init__(self, gd: GameData, rules: Advisor, claude: Advisor | None = None, claude_on=lambda: False):
        self.gd, self.rules, self.claude, self.claude_on = gd, rules, claude, claude_on
        self._lock = threading.Lock()
        self._force = 0
        self._key = None
        self._match = None          # (phase kind, my champion): Claude results never leak across games
        self._claude: tuple | None = None   # (match, Advice)
        self.status = {"state": "off", "error": None}

    def reanalyse(self) -> None:
        with self._lock:
            self._force += 1

    def advise(self, snap: Snapshot, ctx: Context) -> tuple[Advice, dict]:
        advice = guard(self.gd, snap, self.rules.advise(snap, ctx), ctx)
        if not (self.claude and self.claude_on() and snap.me and snap.phase in ("ChampSelect", "InGame")):
            self.status = {"state": "off", "error": None}
            return advice, dict(self.status)
        match = ("cs" if snap.phase == "ChampSelect" else "game", snap.me.name)
        with self._lock:
            key = rethink_key(snap, self._force)
            if key != self._key and self.status["state"] != "running":
                self._key = key
                self.status = {"state": "running", "error": None}
                threading.Thread(target=self._run, args=(snap, ctx, match), daemon=True).start()
            fresh = self._claude if self._claude and self._claude[0] == match else None
        if fresh:
            up = fresh[1]
            for f in self.UPGRADE_FIELDS:
                v = getattr(up, f)
                if v:
                    setattr(advice, f, v)
            advice.source = "claude"
            advice = guard(self.gd, snap, advice, ctx)
        return advice, dict(self.status)

    def _run(self, snap: Snapshot, ctx: Context, match) -> None:
        try:
            res = self.claude.advise(snap, ctx)
            with self._lock:
                self._claude = (match, res)
                self.status = {"state": "done", "error": None}
        except Exception as e:  # rules advice stays
            log.warning("Claude advisor error: %s", str(e)[:300])
            with self._lock:
                self.status = {"state": "error", "error": str(e)[:300]}

    def compare_cards(self, snap: Snapshot, ctx: Context, cards: list[str]) -> dict:
        if self.claude and self.claude_on():
            try:
                return {"ranking": self._clean(self.claude.compare_cards(snap, ctx, cards)), "source": "claude"}
            except Exception as e:
                log.warning("Claude card comparison error: %s", str(e)[:300])
                return {"ranking": self._clean(self.rules.compare_cards(snap, ctx, cards)),
                        "source": "rules", "error": str(e)[:300]}
        return {"ranking": self._clean(self.rules.compare_cards(snap, ctx, cards)), "source": "rules"}

    @staticmethod
    def _clean(ranking: list[dict]) -> list[dict]:
        for r in ranking:
            r["score"] = max(1, min(10, int(float(r.get("score", 5)) + 0.5)))
        return sorted(ranking, key=lambda r: -r["score"])
