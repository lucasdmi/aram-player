# ARAM Player – domain language

Terms used in code, docs and reviews. Keep names in code matching these.

## Game data

- **Match snapshot** – everything the app knows about the current game at one moment, in ONE shape for every
  phase: phase (Lobby, ChampSelect, InGame…), mode (`aram` | `mayhem`), me (champion, owned items), allies,
  bench (champ select only), enemies with their items (in game only), game time. Parts that don't exist in a
  phase are empty, never missing.
- **Game source** – where raw game data comes from. Adapters: **Riot source** (League client API + in-game
  Live Client Data API) and **Recording** (replays saved raw Riot JSON, tick by tick; also powers the demo).
- **Recording** – raw Riot API responses saved per tick while the opt-in Record switch is on; used for the
  demo and for tests. Replay goes through the same parsing as live data.

## Advice

- **Advisor** – produces Advice from a Match snapshot. Two operations: `advise(snapshot)` and
  `compare_cards(snapshot, cards)`. Adapters: **Rules advisor** (MetaSRC + built-in rules, instant, offline)
  and **Claude advisor** (optional, needs the user's API key).
- **Advice** – what the app suggests for one snapshot: team fits (champ select), possible final build
  (exactly ≤ 6 slots incl. boots), suggested next item, situational options with reasons, augment fits.
  Always phrased as options, never orders.
- **Rules first, Claude upgrades** – the Rules advisor always answers immediately; when the Claude advisor is
  on, its Advice replaces the rules Advice once ready; on any Claude error the rules Advice stays.
- **Advice guard** – the single post-processing step every Advice passes, whichever advisor made it: max 6
  slots, no already-owned item suggested, only ARAM-buyable items, damage type matches the player's role.
- **Card comparison** – ranking the 2–4 Mayhem augment cards the player says they were offered.

## Items

- **ARAM-buyable** – an item sold on the ARAM map (map 12) in its base version; mode copies (e.g. Arena 77xxxx)
  don't count.
- **Role** – `ad`, `ap` or `tank`; from champion stats, overridden by what the player is actually building.
