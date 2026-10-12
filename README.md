# ARAM Player

Lightweight, ad-free build helper for **ARAM** and **ARAM Mayhem**.

## Download

| Platform | Download |
|---|---|
| **Windows** | [ARAM-Player-windows.zip](https://github.com/lucasdmi/aram-player/releases/latest/download/ARAM-Player-windows.zip) |
| **Mac** | [ARAM-Player-mac.dmg](https://github.com/lucasdmi/aram-player/releases/latest/download/ARAM-Player-mac.dmg) |

All versions: [Releases](https://github.com/lucasdmi/aram-player/releases). Download the file above, **not** "Source code (zip)".

**Windows:** right-click the zip → **Extract All** → open the folder → double-click **ARAM Player** (`ARAM Player.exe`).
First launch: "Windows protected your PC" → **More info → Run anyway**.

**Mac:** open the `.dmg`, drag **ARAM Player** to Applications. First launch: right-click → **Open → Open**.

Full guide: [HOW-TO-INSTALL.md](HOW-TO-INSTALL.md). Optional AI coach: ⚙️ Settings → your Claude API key.

## What it does
- **Champ select:** detects ARAM / Mayhem, shows your champion's core build, Mayhem augments and runes (from MetaSRC), and lets you preview builds for bench champions.
- **In game:** reads the enemy team and suggests situational items (anti-heal, MR/armor, penetration, anti-CC, anti-burst). Items you already own are highlighted.

The app opens in its own window (developers can also use http://127.0.0.1:8765, or `--lan` for a phone).

## Vanguard / Riot policy safety
This app **only** uses Riot's official, documented local endpoints, the same ones Blitz, Porofessor and U.GG use:

| Source | What | Access |
|---|---|---|
| LCU API (`lockfile` port) | game phase, queue, your champ, bench | read-only GET |
| Live Client Data API (`127.0.0.1:2999`) | champions and items as shown on the scoreboard | read-only GET |
| Data Dragon / MetaSRC | static patch data and builds | internet, cached 24h |

It does **not** read game memory, inject anything, send inputs, or show information you can't already see in game (scoreboard). It never writes to the client. Builds and items are explicitly allowed by Riot's third-party app policy.

## Desktop app (for non-developers)
- Mac: `./build_mac.sh` -> `dist/ARAM-Player-mac.dmg` (share this file).
- Windows: push to GitHub and run the **Build apps** workflow (Actions tab), or `git tag v1.0 && git push --tags`
  to get `ARAM-Player-windows.zip` (+ the Mac .dmg) on a GitHub Release. `build_windows.bat` builds locally on a PC.
- End-user steps: see HOW-TO-INSTALL.md. Settings (optional API key) are stored in `~/.aram_player/config.json`.

## Run (developer)
```bash
cd "ARAM Player"
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m aram_player.main --demo    # test UI without League
python -m aram_player.main           # real use: start before/with the League client
```
If the client isn't found, set `LOL_LOCKFILE=/path/to/League of Legends/lockfile`.

## Architecture (see CONTEXT.md for the terms)
- `match.py` – Match snapshot: one shape for every phase, built only from raw ticks.
- `sources.py` – Game source adapters: `RiotSource` (live) and `RecordingSource` (replay/demo); `Recorder`.
- `advice/` – Advisor interface + Advice guard + engine ("rules first, Claude upgrades");
  `rules.py` (MetaSRC + built-in rules) and `claude.py` (optional, your API key).
- `main.py` – loop: source → snapshot → advice → UI state; web handlers.

## Tests (offline, no League / internet / key needed)
```bash
python -m unittest discover -s tests -v
```
Turn on "Record games" in Settings to save raw games (anonymized) to `~/.aram_player/recordings/`;
copy one to `tests/fixtures/` to turn a real game into a test.

## Tuning the MetaSRC parser
Raw pages are saved to `~/.aram_player/cache/metasrc_*.html`. If items/augments come back empty, those files show the markup so the parser (`aram_player/data.py::_parse_metasrc`) can be adjusted. Delete `metasrc_*.json` to force a refetch.

## Features (current)
- Auto-detects ARAM vs ARAM Mayhem (queue 2400 / gameMode KIWI), champ select and in-game via official APIs.
- Champ select: ranks current champ + bench by team-composition fit (rules + agent), suggests swaps.
- MetaSRC core build (6 slots incl. boots), champion-specific Mayhem augment table (rarity + tier).
- Rules engine: role-aware situational items (anti-heal, MR/armor for AD/AP/tank, pen, anti-burst), ARAM-buyable items only.
- Agent coach (Claude Haiku/Sonnet via ANTHROPIC_API_KEY, optional ANTHROPIC_WORKSPACE_ID, ARAM_MODEL=haiku|sonnet):
  final 6-slot build (max damage + 1 defensive vs biggest threat), next item, augment picks per rarity.
- Mayhem cards: click the 3 offered augments in the grid -> agent ranks them vs the live enemy team.
- Offered augment cards are entered manually by design: they are not exposed by any official API, and
  reading game memory/packets would violate Riot policy and trigger Vanguard.

## Roadmap
- Optional: one-click import of item set / rune page into the client (LCU write; still allowed, off by default).
- Mayhem augment tier list and bench champion ranking.
- Package as a menu-bar/tray app (Tauri or PyInstaller).

---
ARAM Player isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
