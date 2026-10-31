# ARAM Player – install guide (no coding needed)

ARAM Player shows the best build, items and Mayhem augments for your League ARAM games.
It's free, has no ads, and only reads official Riot data. It doesn't change the game, so it's safe with Vanguard.

## Mac
Needs a Mac with an Apple chip (M1 or newer). Check in Apple menu → **About This Mac**: "Chip Apple M…" works, "Intel" doesn't.

1. Open **ARAM-Player-mac.dmg** and drag **ARAM Player** into **Applications**.
2. The first time, macOS blocks the app because it isn't notarized by Apple. Unblock it once:
   - **macOS 15 (Sequoia) or newer:** double-click **ARAM Player**, click **Done** on the warning, then open
     **System Settings → Privacy & Security**, scroll to the bottom and click **Open Anyway** next to
     "ARAM Player was blocked". Confirm with **Open** and your Mac password.
     (Right-click → Open no longer works on these versions.)
   - **macOS 14 or older:** in Applications, **right-click ARAM Player → Open → Open**.
   - Either version: this Terminal command does the same thing in one step.
     Open Terminal, paste the line, press Enter, then open the app normally:
     `xattr -dr com.apple.quarantine "/Applications/ARAM Player.app"`
3. Open League of Legends and queue for ARAM or ARAM Mayhem. ARAM Player detects the game automatically.

If nothing opens and no warning appears, the app started and stopped: the reason is in `~/.aram_player/app.log`.

## Windows
1. Unzip **ARAM-Player-windows.zip** (right-click → Extract All), for example into `Documents`.
2. Open the folder and double-click **ARAM Player.exe**.
3. If Windows shows "Windows protected your PC": click **More info → Run anyway** (only the first time).
4. Open League of Legends and queue for ARAM or ARAM Mayhem.

## Using it
- **Champ select:** shows the best pick for your team from your champion and the bench, plus the build.
- **In game:** shows the 6-item build for this match, items against the enemy team, and Mayhem augments.
- **Mayhem cards:** when cards are offered, click the 3 you see in the augment grid, then **Rank for this match**.
- **Optional AI coach:** ⚙️ Settings → paste a Claude API key → tick "Use AI coach" → **Test key**.
  Without a key everything else still works.

Tip: put the window on a second screen, or next to the game in windowed mode.
