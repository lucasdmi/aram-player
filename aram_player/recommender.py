"""Offline rules engine: adapt the build to the enemy team composition.

Uses only what you can see on the scoreboard (champions + their items).
"""
from __future__ import annotations

from .data import GameData

HEALERS = {
    "Aatrox", "Soraka", "Yuumi", "Sona", "Nami", "Seraphine", "Vladimir", "Swain", "Sylas",
    "DrMundo", "Warwick", "Fiddlesticks", "Briar", "Illaoi", "Olaf", "Darius", "Volibear",
    "Maokai", "Aphelios", "Samira", "Kayn", "Renekton", "Trundle", "Senna", "Milio",
    "Renata", "Taric", "Zac", "Sett", "Nidalee", "Irelia", "Yone", "Gwen", "Vayne", "Kindred",
}
HEAVY_CC = {
    "Leona", "Nautilus", "Morgana", "Lux", "Amumu", "Sejuani", "Ashe", "Varus", "Malphite",
    "Rell", "Alistar", "Thresh", "Blitzcrank", "Lissandra", "Zyra", "Neeko", "Maokai", "Veigar",
    "Annie", "Brand", "Galio", "Rakan", "Taric", "Sona", "Seraphine", "Jhin", "Xerath", "Zoe",
}

# Item name candidates per need; first one that exists in this patch wins.
NEEDS = {
    "antiheal_ad": ["Mortal Reminder", "Chempunk Chainsword", "Executioner's Calling"],
    "antiheal_ap": ["Morellonomicon", "Oblivion Orb"],
    "antiheal_tank": ["Thornmail", "Bramble Vest"],
    "armor_pen": ["Lord Dominik's Regards", "Black Cleaver", "Serylda's Grudge"],
    "magic_pen": ["Void Staff", "Liandry's Torment", "Cryptbloom"],
    "mr": ["Force of Nature", "Kaenic Rookern", "Spirit Visage"],          # tanks
    "mr_ad": ["Maw of Malmortius", "Wit's End", "Guardian Angel"],         # AD carries
    "mr_ap": ["Banshee's Veil", "Mercury's Treads"],                        # AP carries
    "armor": ["Randuin's Omen", "Frozen Heart", "Dead Man's Plate"],              # tanks
    "armor_ad": ["Death's Dance", "Guardian Angel", "Immortal Shieldbow"],         # AD carries
    "armor_ap": ["Zhonya's Hourglass", "Seraph's Embrace"],                        # AP carries
    "anti_cc_boots": ["Mercury's Treads"],
    "qss": ["Mercurial Scimitar", "Quicksilver Sash"],
    "anti_burst": ["Zhonya's Hourglass", "Guardian Angel", "Sterak's Gage", "Shieldbow"],
}


def _role(champ: dict) -> str:
    tags = champ.get("tags", [])
    info = champ.get("info", {})
    if "Tank" in tags:
        return "tank"
    if info.get("magic", 0) > info.get("attack", 0):
        return "ap"
    return "ad"


def my_role(gd: GameData, champ: dict, owned_ids: set | None = None) -> str:
    """Role from champion stats, overridden by what the player is actually building."""
    base = _role(champ)
    if base == "tank":
        return base
    ap = ad = 0
    for iid in owned_ids or ():
        st = gd.items.get(iid, {}).get("stats", {})
        ap += "FlatMagicDamageMod" in st
        ad += "FlatPhysicalDamageMod" in st
    if ap >= 2 and ap > ad:
        return "ap"
    if ad >= 2 and ad > ap:
        return "ad"
    return base


def _pick(gd: GameData, need: str, role: str) -> dict | None:
    for name in NEEDS[need]:
        ref = gd.item_ref(name)
        if not ref:
            continue
        stats = gd.items[ref["id"]].get("stats", {})
        # strict: never offer an AD item to an AP champion or vice versa
        if role == "ad" and "FlatMagicDamageMod" in stats:
            continue
        if role == "ap" and "FlatPhysicalDamageMod" in stats:
            continue
        return ref
    return None


def analyse(gd: GameData, my_champ: dict, enemy_champs: list[dict], owned_ids: set | None = None) -> dict:
    role = my_role(gd, my_champ, owned_ids)
    n = max(len(enemy_champs), 1)
    ap = sum(1 for c in enemy_champs if _role(c) == "ap" and "Tank" not in c.get("tags", []))
    tanks = sum(1 for c in enemy_champs if "Tank" in c.get("tags", []))
    assassins = sum(1 for c in enemy_champs if "Assassin" in c.get("tags", []))
    healers = [c["name"] for c in enemy_champs if c["id"] in HEALERS]
    cc = [c["name"] for c in enemy_champs if c["id"] in HEAVY_CC]

    tips, picks = [], []

    def add(need: str, why: str):
        ref = _pick(gd, need, role)
        if ref and ref["id"] not in (owned_ids or set()) and all(p["id"] != ref["id"] for p in picks):
            picks.append({**ref, "why": why, "kind": "defensive" if need in DEFENSIVE_NEEDS else "utility"})

    if len(healers) >= 2:
        need = {"ad": "antiheal_ad", "ap": "antiheal_ap", "tank": "antiheal_tank"}[role]
        add(need, f"Anti-heal vs {', '.join(healers)}")
    if tanks >= 2:
        if role != "tank":
            add("armor_pen" if role == "ad" else "magic_pen", f"{tanks} tanks on enemy team")
    if ap / n >= 0.6:
        add({"tank": "mr", "ad": "mr_ad", "ap": "mr_ap"}[role], f"Enemy is {ap}/{n} magic damage")
        if role == "ad" or role == "tank":
            tips.append("Mercury's Treads are strong here.")
    elif ap / n <= 0.4:
        add({"tank": "armor", "ad": "armor_ad", "ap": "armor_ap"}[role], f"Enemy is mostly physical ({n - ap}/{n})")
    if len(cc) >= 3:
        add("anti_cc_boots", f"Heavy CC: {', '.join(cc)}")
        if role == "ad" and "Marksman" in my_champ.get("tags", []):
            add("qss", "Cleanse hard CC")
    if assassins >= 2 and role != "tank":
        add("anti_burst", f"{assassins} assassins")

    summary = {
        "enemy_ap": ap, "enemy_ad": n - ap, "tanks": tanks,
        "assassins": assassins, "healers": healers, "heavy_cc": cc, "my_role": role,
    }
    return {"summary": summary, "situational": picks, "tips": tips}


# ----------------------------------------------------------------- champ select
ENGAGE = HEAVY_CC | {"Sejuani", "Zac", "Ornn", "Jarvan IV", "JarvanIV", "Vi", "Wukong", "MonkeyKing",
                     "Kennen", "Diana", "Orianna", "Rakan", "Skarner", "Poppy"}


def _profile(champs: list[dict]) -> dict:
    p = {"frontline": 0, "ap": 0, "ad": 0, "engage": 0, "sustain": 0, "poke": 0}
    for c in champs:
        tags = c.get("tags", [])
        if "Tank" in tags or ("Fighter" in tags and c.get("info", {}).get("defense", 0) >= 5):
            p["frontline"] += 1
        p["ap" if _role(c) == "ap" else "ad"] += 1 if "Tank" not in tags else 0
        p["engage"] += c["id"] in ENGAGE
        p["sustain"] += c["id"] in HEALERS or "Support" in tags
        p["poke"] += ("Mage" in tags or "Marksman" in tags) and c.get("info", {}).get("defense", 5) <= 3
    return p


def comp_fit(candidate: dict, allies: list[dict]) -> tuple[int, list[str]]:
    """Score 0-100 for how well `candidate` completes the allied team, with reasons."""
    team = _profile(allies)
    tags = candidate.get("tags", [])
    score, why = 50, []
    if team["frontline"] == 0 and ("Tank" in tags or "Fighter" in tags):
        score += 25; why.append("Team has no frontline")
    elif team["frontline"] >= 2 and "Tank" in tags:
        score -= 10; why.append("Team already has 2+ frontliners")
    dmg = "ap" if _role(candidate) == "ap" else "ad"
    if "Tank" not in tags:
        other = "ad" if dmg == "ap" else "ap"
        if team[dmg] >= 3 and team[other] <= 1:
            score -= 20; why.append(f"Team is already {team[dmg]} {dmg.upper()} - damage too one-sided")
        elif team[dmg] == 0 and len(allies) >= 2:
            score += 15; why.append(f"Team lacks {dmg.upper()} damage")
    if team["engage"] == 0 and candidate["id"] in ENGAGE:
        score += 15; why.append("Adds engage/CC the team lacks")
    if team["sustain"] == 0 and (candidate["id"] in HEALERS or "Support" in tags):
        score += 10; why.append("Adds sustain")
    if team["poke"] >= 2 and ("Mage" in tags or "Marksman" in tags) and team["frontline"] == 0:
        score -= 10; why.append("Lots of squishy poke, no one to protect it")
    return max(0, min(100, score)), why or ["Neutral fit"]


def rank_picks(options: list[dict], allies: list[dict]) -> list[dict]:
    ranked = []
    for c in options:
        sc, why = comp_fit(c, allies)
        ranked.append({"id": c["id"], "name": c["name"], "score": sc, "why": why})
    return sorted(ranked, key=lambda r: -r["score"])


# ----------------------------------------------------------------- no-AI final build
DEFENSIVE_NEEDS = ("mr", "mr_ad", "mr_ap", "armor", "armor_ad", "armor_ap", "anti_burst", "qss")


def final_build(gd: GameData, my_champ: dict, core: list[dict], situational: list[dict],
                owned_ids: set) -> dict:
    """6 slots: boots + damage core from MetaSRC, with up to 1 situational utility item
    (anti-heal / penetration) and 1 defensive item swapped in for the last core damage items.
    Tanks may take 2 defensive picks. Owned items always stay."""
    role = my_role(gd, my_champ, owned_ids)
    is_boots = lambda i: "Boots" in gd.items.get(i["id"], {}).get("tags", [])
    boots = next((i for i in core if is_boots(i)), None)
    damage = [i for i in core if not is_boots(i)]

    defensive = [i for i in situational if i.get("kind") == "defensive"][: (2 if role == "tank" else 1)]
    utility = [i for i in situational if i.get("kind") != "defensive"][:1]
    swaps = utility + defensive

    keep_damage = damage[: max(0, 5 - len(swaps))]
    plan = ([boots] if boots else []) + keep_damage + swaps
    # owned completed items stay; fill up to 6
    owned_refs = [{"id": iid, "name": gd.items[iid]["name"], "icon": gd.item_icon(iid)}
                  for iid in owned_ids if iid in gd.items and (gd.is_completed_item(iid) or
                  "Boots" in gd.items[iid].get("tags", []))]
    final, seen = [], set()
    for it in owned_refs + plan + damage:
        if it and it["id"] not in seen and len(final) < 6:
            seen.add(it["id"]); final.append(it)
    to_buy = [i for i in final if i["id"] not in owned_ids]
    return {"final_build": final, "build_order": to_buy,
            "next_item": to_buy[0]["name"] if to_buy else "Build complete",
            "why": [f'{i["name"]}: {i["why"]}' for i in swaps if i["id"] in seen]}
