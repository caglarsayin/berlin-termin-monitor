"""Shared browser settings and runtime paths.

Runtime files live beside the launcher unless TERMIN_DATA_DIR points elsewhere
(e.g. a mounted volume in a container)."""

import os
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent.parent
SOURCE_FILE = SCRIPT_DIR / "termin_monitor.py"
DATA_DIR = Path(os.environ.get("TERMIN_DATA_DIR") or SCRIPT_DIR)


CONFIG_FILE = DATA_DIR / "termin_config.json"
DEBUG_DIR = DATA_DIR / "debug"
SRC_MTIME = os.path.getmtime(SOURCE_FILE)
LOG_FILE = DATA_DIR / "termin_monitor.log"
DOCTOLIB_LEDGER_FILE = DATA_DIR / ".doctolib_ledger.json"
DL_PROFILE_DIR = DATA_DIR / ".dl_profile"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
