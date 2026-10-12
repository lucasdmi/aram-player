"""Static game data (Data Dragon) + MetaSRC Mayhem/ARAM builds, cached on disk.

MetaSRC is fetched lazily (only champions you actually see), at most once per day
per champion, with a polite delay. Use for personal use and respect their ToS.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin
from pathlib import Path

import requests

from .log import log
from bs4 import BeautifulSoup

try:  # browser-like TLS fingerprint; MetaSRC blocks plain python-requests (403)
    from curl_cffi import requests as browser_requests
except ImportError:
    browser_requests = None


def _browser_get(url: str):
    headers = {"Accept-Language": "en-US,en;q=0.9",
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    if browser_requests:
        return browser_requests.get(url, impersonate="chrome", headers=headers, timeout=20)
    return requests.get(url, headers={**headers, "User-Agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"}, timeout=15)

CACHE = Path.home() / ".aram_player" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
TTL = 24 * 3600
UA = {"User-Agent": "Mozilla/5.0 (ARAM-Player personal build helper)"}
DD = "https://ddragon.leagueoflegends.com"

SLUG_OVERRIDES = {
    "JarvanIV": "jarvan",
    "Nunu": "nunu",
    "Renata": "renata-glasc",
    "MonkeyKing": "wukong",
}

_last_fetch = 0.0
_failures: dict[str, tuple[float, dict]] = {}
FAIL_BACKOFF = 600


def _cached_json(name: str, url: str, ttl: int = TTL):
    """Fresh cache -> network -> stale cache. The app still starts offline if it has run once before."""
    f = CACHE / name
    if f.exists() and time.time() - f.stat().st_mtime < ttl:
        return json.loads(f.read_text())
    try:
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        if f.exists():
            log.warning("Data Dragon %s unreachable (%s); using cached copy", name, e)
            return json.loads(f.read_text())
        raise
    f.write_text(json.dumps(data))
    return data


def _prune_old_patches(version: str) -> None:
    """Patch-keyed cache files from older patches are dead weight; remove them."""
    for f in CACHE.glob("*_*.json"):
        if f.name.startswith(("champion_", "item_", "runes_", "metasrc_v4_", "metasrc_v5_")) and version not in f.name:
            try:
                f.unlink()
            except OSError:
                pass


class GameData:
    def __init__(self) -> None:
        version = _cached_json("versions.json", f"{DD}/api/versions.json")[0]
        v = version
        champs = _cached_json(f"champion_{v}.json", f"{DD}/cdn/{v}/data/en_US/champion.json")["data"]
        items = _cached_json(f"item_{v}.json", f"{DD}/cdn/{v}/data/en_US/item.json")["data"]
        runes = _cached_json(f"runes_{v}.json", f"{DD}/cdn/{v}/data/en_US/runesReforged.json")
        self._load(version, champs, items, runes)
        _prune_old_patches(version)

    @classmethod
    def from_data(cls, version: str, champs: dict, items: dict, runes: list | None = None) -> "GameData":
        """Build from already-loaded Data Dragon dicts (tests, offline)."""
        gd = cls.__new__(cls)
        gd._load(version, champs, items, runes or [])
        return gd

    def _load(self, version: str, champs: dict, items: dict, runes: list) -> None:
        self.version = version
        self._builds: dict[str, tuple[float, dict]] = {}   # in-memory memo: the loop asks every few seconds
        self.champ_by_key = {int(c["key"]): c for c in champs.values()}
        self.champ_by_name = {c["name"].lower(): c for c in champs.values()}
        self.champ_by_name.update({c["id"].lower(): c for c in champs.values()})
        self.items = items
        # Items buyable on the ARAM map. Data Dragon also contains mode copies of items
        # (e.g. Arena 77xxxx); if a base item (id < 10000) with that name exists, only the base
        # counts - so Guardian Angel is excluded when the base GA isn't on map 12.
        base_ids = {}
        for iid, i in items.items():
            if int(iid) < 10000:
                base_ids.setdefault(i["name"].lower(), iid)
        self.aram_ids = set()
        for iid, i in items.items():
            name = i["name"].lower()
            if name in base_ids and iid != base_ids[name]:
                continue
            if (i.get("maps", {}).get("12", False) and i.get("gold", {}).get("purchasable", True)
                    and i.get("inStore", True) is not False):
                self.aram_ids.add(iid)
        self.item_by_name = {items[iid]["name"].lower(): (iid, items[iid]) for iid in self.aram_ids}
        self.rune_names = {r["name"].lower() for tree in runes for slot in tree["slots"] for r in slot["runes"]}
        self.rune_names |= {tree["name"].lower() for tree in runes}

    # ------------------------------------------------------------------ helpers
    def champ(self, key_or_name) -> dict | None:
        if isinstance(key_or_name, int):
            return self.champ_by_key.get(key_or_name)
        return self.champ_by_name.get(str(key_or_name).lower())

    def champ_icon(self, champ: dict) -> str:
        return f"{DD}/cdn/{self.version}/img/champion/{champ['image']['full']}"

    def item_icon(self, item_id: str) -> str:
        return f"{DD}/cdn/{self.version}/img/item/{item_id}.png"

    def is_completed_item(self, iid: str) -> bool:
        if hasattr(self, "aram_ids") and iid not in self.aram_ids:
            return False
        it = self.items.get(iid, {})
        return not it.get("into") and it.get("gold", {}).get("total", 0) >= 2000

    def is_boots(self, iid: str) -> bool:
        return "Boots" in self.items.get(str(iid), {}).get("tags", [])

    def is_aram_buyable(self, iid: str) -> bool:
        return str(iid) in self.aram_ids

    def damage_type(self, iid: str) -> str | None:
        """'ad', 'ap', 'hybrid' or None (no damage stat)."""
        st = self.items.get(str(iid), {}).get("stats", {})
        ad, ap = "FlatPhysicalDamageMod" in st, "FlatMagicDamageMod" in st
        return "hybrid" if ad and ap else "ad" if ad else "ap" if ap else None

    def item_ref_by_id(self, iid: str) -> dict | None:
        it = self.items.get(str(iid))
        return {"id": str(iid), "name": it["name"], "icon": self.item_icon(str(iid))} if it else None

    def item_ref(self, name: str) -> dict | None:
        hit = self.item_by_name.get(name.lower())
        if not hit:
            return None
        iid, it = hit
        return {"id": iid, "name": it["name"], "icon": self.item_icon(iid)}

    @staticmethod
    def slug(champ: dict) -> str:
        if champ["id"] in SLUG_OVERRIDES:
            return SLUG_OVERRIDES[champ["id"]]
        return re.sub(r"[^a-z0-9]", "", champ["name"].lower())

    # ------------------------------------------------------------------ MetaSRC
    def metasrc_build(self, champ: dict, mode: str = "mayhem") -> dict:
        """mode: 'mayhem' or 'aram'. Returns {items, runes, augments, source, error?}."""
        slug = self.slug(champ)
        # keyed by patch: a new patch invalidates builds immediately (bump v5 when the parser changes)
        f = CACHE / f"metasrc_v5_{self.version}_{mode}_{slug}.json"
        memo = self._builds.get(f.name)
        if memo and time.time() - memo[0] < TTL:
            return memo[1]
        if f.exists() and time.time() - f.stat().st_mtime < TTL:
            result = json.loads(f.read_text())
            self._builds[f.name] = (f.stat().st_mtime, result)
            return result

        fail = _failures.get(f.name)
        if fail and time.time() - fail[0] < FAIL_BACKOFF:
            return fail[1]
        url = f"https://www.metasrc.com/lol/{mode}/champions/{slug}/build"
        result = {"items": [], "runes": [], "augments": [], "source": url}
        global _last_fetch
        try:
            wait = 1.5 - (time.time() - _last_fetch)
            if wait > 0:
                time.sleep(wait)
            _last_fetch = time.time()
            r = _browser_get(url)
            r.raise_for_status()
            (CACHE / f"metasrc_{mode}_{slug}.html").write_text(r.text)  # for parser debugging
            result.update(self._parse_metasrc(r.text))
            if not result["items"]:
                # page loaded but nothing parsed: MetaSRC changed its layout. Don't cache an empty build.
                raise ValueError("parser found no items (MetaSRC layout changed?)")
            log.info("MetaSRC %s/%s: %d items, %d augments", mode, slug,
                     len(result.get("items", [])), len(result.get("augment_table", [])))
        except Exception as e:  # network/parse failures fall back to rules engine
            log.warning("MetaSRC %s/%s failed: %s", mode, slug, e)
            result["error"] = str(e)
            _failures[f.name] = (time.time(), result)
            return result
        f.write_text(json.dumps(result))
        self._builds[f.name] = (time.time(), result)
        return result

    def augment_catalog(self) -> list[dict]:
        """All Mayhem augments in MetaSRC tier-list order: [{name, icon, rank}]."""
        f = CACHE / "metasrc_v2_augment_catalog.json"
        if f.exists() and time.time() - f.stat().st_mtime < TTL:
            return json.loads(f.read_text())
        fail = _failures.get(f.name)
        if fail and time.time() - fail[0] < FAIL_BACKOFF:
            return fail[1]
        try:
            r = _browser_get("https://www.metasrc.com/lol/mayhem/tier-list/augments")
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            out, seen = [], set()
            for img in soup.find_all("img"):
                src = img.get("data-src") or img.get("src") or ""
                alt = (img.get("alt") or "").strip()
                if "/augments/" in src and alt and alt not in seen:
                    seen.add(alt)
                    out.append({"name": alt, "icon": urljoin("https://www.metasrc.com/", src),
                                "rank": len(out) + 1})
            if not out:
                raise ValueError("no augments found on tier list page")
            f.write_text(json.dumps(out))
            return out
        except Exception:
            _failures[f.name] = (time.time(), [])
            return []

    def _parse_metasrc(self, html: str) -> dict:
        """MetaSRC image paths identify the type: /augments/<x>/, /items/<slug>-<id>.png, /spells/.
        'Core Item:' images belong to the build-variant selector and are skipped."""
        soup = BeautifulSoup(html, "html.parser")
        items, boots, augments, spells = [], None, [], []
        seen_items, seen_aug, seen_sp = set(), set(), set()
        for img in soup.find_all("img"):
            alt = (img.get("alt") or "").strip()
            src = img.get("data-src") or img.get("src") or ""
            if "/augments/" in src:
                if alt and alt not in seen_aug:
                    seen_aug.add(alt)
                    augments.append({"name": alt, "icon": urljoin("https://www.metasrc.com/", src)})
            elif "/spells/" in src:
                if alt and alt not in seen_sp:
                    seen_sp.add(alt)
                    spells.append(alt)
            elif "/items/" in src and not alt.startswith("Core Item"):
                m = re.search(r"-(\d+)\.png", src)
                if not m:
                    continue
                iid = m.group(1)
                it = self.items.get(iid)
                if not it or iid in seen_items:
                    continue
                seen_items.add(iid)
                ref = {"id": iid, "name": it["name"], "icon": self.item_icon(iid)}
                if "Boots" in it.get("tags", []) and it.get("gold", {}).get("total", 0) >= 1000:
                    boots = boots or ref
                elif self.is_completed_item(iid) and len(items) < 6:
                    items.append(ref)
        if boots:
            items = items[:5]
            items.insert(min(2, len(items)), boots)
        return {"items": items[:6],  # 6 inventory slots, boots included
                "augments": augments[:10], "spells": spells[:4], "runes": [],
                "augment_table": self._parse_augment_table(soup)}

    TIER_ORDER = {"S+": 0, "S": 1, "A": 2, "B": 3, "C": 4, "D": 5}
    RARITY = {"1": "Silver", "2": "Gold", "3": "Prismatic"}

    def _parse_augment_table(self, soup) -> list[dict]:
        """Champion-specific augment tiers: MetaSRC embeds them as JSON in
        <script id="ArenaWidget_row_data" type="application/json">."""
        tag = soup.find("script", id="ArenaWidget_row_data")
        if not tag or not tag.string:
            return []
        try:
            rows = json.loads(tag.string)
        except ValueError:
            return []
        out = []
        for r in rows:
            v = r.get("values", {})
            out.append({
                "name": v.get("name") or r.get("title"),
                "rarity": self.RARITY.get(str(v.get("rarity")), r.get("displays", {}).get("rarity", "?")),
                "tier": v.get("tier") or r.get("subtitle") or "?",
                "icon": r.get("image"),
            })
        out.sort(key=lambda a: (self.TIER_ORDER.get(a["tier"], 9), a["name"]))
        return out
