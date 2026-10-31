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


# ----------------------------------------------------------------- ADC archetypes
# Marksmen build very differently; the same "need" (anti-tank, defence...) maps to different items.
ADC_STYLE = {
    # crit carries
    "Jinx": "crit", "Caitlyn": "crit", "Draven": "crit", "Jhin": "crit", "Tristana": "crit",
    "Samira": "crit", "Xayah": "crit", "Aphelios": "crit", "Sivir": "crit", "MissFortune": "crit",
    "Ashe": "crit", "Nilah": "crit", "Yunara": "crit", "Smolder": "crit", "Zeri": "crit",
    "Lucian": "crit", "Twitch": "crit", "Senna": "crit", "Mel": "crit",
    # on-hit / attack speed
    "Vayne": "onhit", "KogMaw": "onhit", "Kalista": "onhit", "Kaisa": "onhit", "Corki": "onhit",
    "Kindred": "onhit", "Quinn": "onhit", "Kayle": "onhit",
    # lethality / caster ADCs
    "Ezreal": "lethality", "Varus": "lethality", "Graves": "lethality",
}
ADC_NEEDS = {
    "crit": {
        "armor_pen": ["Lord Dominik's Regards", "Mortal Reminder"],
        "antiheal_ad": ["Mortal Reminder"],
        "armor_ad": ["Immortal Shieldbow", "Guardian Angel", "Death's Dance"],
        "mr_ad": ["Maw of Malmortius", "Wit's End", "Guardian Angel"],
        "anti_burst": ["Immortal Shieldbow", "Guardian Angel", "Bloodthirster"],
    },
    "onhit": {
        "armor_pen": ["Blade of The Ruined King", "Kraken Slayer", "Lord Dominik's Regards"],
        "antiheal_ad": ["Mortal Reminder", "Chempunk Chainsword"],
        "armor_ad": ["Randuin's Omen", "Death's Dance", "Guardian Angel"],
        "mr_ad": ["Wit's End", "Maw of Malmortius"],
        "anti_burst": ["Guardian Angel", "Immortal Shieldbow", "Mercurial Scimitar"],
    },
    "lethality": {
        "armor_pen": ["Serylda's Grudge", "Black Cleaver", "Lord Dominik's Regards"],
        "antiheal_ad": ["Chempunk Chainsword", "Executioner's Calling", "Mortal Reminder"],
        "armor_ad": ["Death's Dance", "Guardian Angel"],
        "mr_ad": ["Maw of Malmortius", "Edge of Night"],
        "anti_burst": ["Edge of Night", "Guardian Angel", "Death's Dance"],
    },
}


def adc_style(champ: dict) -> str | None:
    if champ.get("id") in ADC_STYLE:
        return ADC_STYLE[champ["id"]]
    return "crit" if "Marksman" in champ.get("tags", []) and _role(champ) == "ad" else None


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


def _pick(gd: GameData, need: str, role: str, style: str | None = None) -> dict | None:
    names = ADC_NEEDS.get(style or "", {}).get(need, []) + NEEDS[need] if role == "ad" else NEEDS[need]
    for name in names:
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


def _kda(kda: str) -> tuple[int, int, int]:
    try:
        k, d, a = (int(x) for x in (kda or "0/0/0").split("/"))
        return k, d, a
    except ValueError:
        return 0, 0, 0


def _enemy_profile(gd: GameData, champ: dict, item_ids=(), level: int = 0, kda: str = "") -> dict:
    """What this enemy *actually* is right now: damage type from their items (falls back to
    champion stats), sustain/tankiness from item stats, and a threat weight from KDA + gold."""
    ap_items = ad_items = vamp = tanky = gold = 0
    for iid in item_ids or ():
        it = gd.items.get(str(iid), {})
        st, tags = it.get("stats", {}), it.get("tags", [])
        if not gd.is_completed_item(str(iid)) and "Boots" not in tags:
            continue
        gold += it.get("gold", {}).get("total", 0)
        ap_items += "FlatMagicDamageMod" in st
        ad_items += "FlatPhysicalDamageMod" in st
        vamp += ("LifeSteal" in tags or "SpellVamp" in tags or "PercentLifeStealMod" in st)
        tanky += ("FlatHPPoolMod" in st and ("FlatArmorMod" in st or "FlatSpellBlockMod" in st)
                  and "FlatMagicDamageMod" not in st and "FlatPhysicalDamageMod" not in st)
    role = _role(champ)
    if role != "tank":
        if ap_items >= 2 and ap_items > ad_items:
            role = "ap"
        elif ad_items >= 2 and ad_items > ap_items:
            role = "ad"
    if tanky >= 2:
        role = "tank"
    k, d, a = _kda(kda)
    # 1.0 = average; fed enemies up to 2.5, feeding ones down to 0.5
    threat = 1.0 + 0.12 * (k - d) + 0.03 * a + gold / 20000
    threat = max(0.5, min(2.5, threat))
    return {"name": champ["name"], "role": role, "tank": role == "tank" or "Tank" in champ.get("tags", []),
            "assassin": "Assassin" in champ.get("tags", []),
            "healer": champ["id"] in HEALERS or vamp >= 2, "vamp_items": vamp,
            "cc": champ["id"] in HEAVY_CC, "threat": round(threat, 2), "kda": (k, d, a), "level": level}


def analyse(gd: GameData, my_champ: dict, enemy_champs: list[dict], owned_ids: set | None = None,
            enemy_players: list | None = None) -> dict:
    """enemy_players (match.Player list) is optional; when given, their items/KDA/level
    refine the read of the enemy team. Without it this behaves like the champion-only version."""
    role = my_role(gd, my_champ, owned_ids)
    style = adc_style(my_champ) if role == "ad" else None
    if enemy_players:
        profs = [_enemy_profile(gd, p.champion, p.item_ids, p.level, p.kda) for p in enemy_players]
    else:
        profs = [_enemy_profile(gd, c) for c in enemy_champs]
    n = max(len(profs), 1)
    total = sum(p["threat"] for p in profs) or 1.0
    # threat-weighted shares: a fed AP carry counts more than a 0/8 one
    ap_share = sum(p["threat"] for p in profs if p["role"] == "ap" and not p["tank"]) / total
    ap = sum(1 for p in profs if p["role"] == "ap" and not p["tank"])
    tanks = sum(1 for p in profs if p["tank"])
    assassins = sum(1 for p in profs if p["assassin"])
    healers = [p["name"] for p in profs if p["healer"]]
    heavy_vamp = [p["name"] for p in profs if p["vamp_items"] >= 2]
    cc = [p["name"] for p in profs if p["cc"]]
    fed = sorted((p for p in profs if p["threat"] >= 1.6), key=lambda p: -p["threat"])

    tips, picks = [], []

    def add(need: str, why: str):
        ref = _pick(gd, need, role, style)
        if ref and ref["id"] not in (owned_ids or set()) and all(p["id"] != ref["id"] for p in picks):
            picks.append({**ref, "why": why, "kind": "defensive" if need in DEFENSIVE_NEEDS else "utility"})

    def defend_vs(dmg: str, why: str):
        if dmg == "ap":
            add({"tank": "mr", "ad": "mr_ad", "ap": "mr_ap"}[role], why)
        else:
            add({"tank": "armor", "ad": "armor_ad", "ap": "armor_ap"}[role], why)

    # 1) the fed enemy is the priority: build against whoever is actually carrying
    if fed and fed[0]["role"] in ("ap", "ad") and not fed[0]["tank"]:
        f = fed[0]
        k, d, a = f["kda"]
        defend_vs(f["role"], f"{f['name']} is fed ({k}/{d}/{a}, {f['role'].upper()})")
        tips.append(f"Focus/avoid {f['name']} - biggest threat right now.")
    # 2) anti-heal: 2+ sustain sources, or one fed one
    if len(healers) >= 2 or any(p["healer"] and p["threat"] >= 1.6 for p in profs):
        need = {"ad": "antiheal_ad", "ap": "antiheal_ap", "tank": "antiheal_tank"}[role]
        extra = f" (building lifesteal: {', '.join(heavy_vamp)})" if heavy_vamp else ""
        add(need, f"Anti-heal vs {', '.join(healers)}{extra}")
    # 3) penetration vs real tanks (by champion or by tank items)
    if tanks >= 2 and role != "tank":
        add("armor_pen" if role == "ad" else "magic_pen", f"{tanks} tanky enemies")
    # 4) overall damage split, weighted by threat
    if ap_share >= 0.6:
        defend_vs("ap", f"Enemy damage is ~{round(ap_share * 100)}% magic (by threat)")
        if role in ("ad", "tank"):
            tips.append("Mercury's Treads are strong here.")
    elif ap_share <= 0.4:
        defend_vs("ad", f"Enemy damage is ~{round((1 - ap_share) * 100)}% physical (by threat)")
    if len(cc) >= 3:
        add("anti_cc_boots", f"Heavy CC: {', '.join(cc)}")
        if style:
            add("qss", "Cleanse hard CC")
    if role != "tank" and (assassins >= 2 or any(p["assassin"] and p["threat"] >= 1.6 for p in profs)):
        add("anti_burst", f"{assassins} assassin(s)" + (" - one is fed" if assassins < 2 else ""))

    if style:
        divers = [p["name"] for p in profs if p["assassin"] or (p["tank"] and p["cc"])]
        if len(divers) >= 2:
            tips.append(f"{', '.join(divers)} will dive you - stay behind your frontline.")
        if tanks >= 2 and style == "lethality":
            tips.append("Lethality falls off vs tanks: poke the squishies, let others peel the frontline.")

    summary = {
        "adc_style": style,
        "enemy_ap": ap, "enemy_ad": n - ap, "enemy_ap_share": round(ap_share, 2), "tanks": tanks,
        "assassins": assassins, "healers": healers, "heavy_cc": cc, "my_role": role,
        "fed": [p["name"] for p in fed],
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


# ----------------------------------------------------------------- shopping list
def _price(gd: GameData, iid: str, pool) -> int:
    """Shop price of `iid` right now. Owned components are consumed from `pool` and cost nothing."""
    if pool[iid] > 0:
        pool[iid] -= 1
        return 0
    it = gd.items.get(iid)
    if not it:
        return 0
    parts = [p for p in it.get("from") or [] if p in gd.items]
    combine = it["gold"]["total"] - sum(gd.items[p]["gold"]["total"] for p in parts)
    return max(0, combine) + sum(_price(gd, p, pool) for p in parts)


def _fill(gd: GameData, iid: str, pool, left: int, buy: list[dict]) -> int:
    """Buy as much of `iid` as `left` gold allows, biggest affordable piece first. Returns the gold left."""
    price = _price(gd, iid, pool.copy())
    if price <= left:
        _price(gd, iid, pool)                      # commit: consume the components it uses
        if price > 0:
            buy.append({"id": iid, "name": gd.items[iid]["name"], "icon": gd.item_icon(iid), "cost": price})
            pool[iid] += 1                         # bought: it now counts as owned
        return left - price
    parts = [p for p in gd.items.get(iid, {}).get("from") or [] if p in gd.items]
    for p in sorted(parts, key=lambda p: -gd.items[p]["gold"]["total"]):
        left = _fill(gd, p, pool, left, buy)
    return left


def shopping_list(gd: GameData, plan: list[dict], owned: list[str], gold: float) -> dict:
    """What to buy with the gold in hand, following `plan` (the final build in buying order).
    In ARAM you only shop while dead, so this is the answer to "I just died, what do I click?".
    Owned components count toward the price, like in the shop. Stops at the first item that
    can't be completed, after buying the biggest pieces of it that fit."""
    from collections import Counter
    pool = Counter(owned)
    buy: list[dict] = []
    left = int(gold)
    toward, missing = "", 0
    for it in plan:
        iid = it.get("id")
        if not iid or it.get("owned") or iid not in gd.items:
            continue
        price, before = _price(gd, iid, pool.copy()), len(buy)
        left = _fill(gd, iid, pool, left, buy)
        missing = price - sum(b["cost"] for b in buy[before:])   # every piece bought lowers the price by its cost
        if missing > 0:
            toward = it["name"]
            break
    return {"gold": int(gold), "buy": buy, "spent": sum(b["cost"] for b in buy), "left": left,
            "toward": toward, "missing": missing}
