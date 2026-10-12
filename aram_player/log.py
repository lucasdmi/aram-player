"""App log at ~/.aram_player/app.log (max ~1 MB x 3 files). Never logs API keys or passwords."""
from __future__ import annotations

import logging
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PATH = Path.home() / ".aram_player" / "app.log"
log = logging.getLogger("aram_player")

if not log.handlers:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)
    log.info("---- start: %s %s, Python %s", platform.system(), platform.release(), sys.version.split()[0])
