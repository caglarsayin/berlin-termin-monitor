"""Shared browser settings and runtime paths beside the original launcher."""

import os
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent.parent
SOURCE_FILE = SCRIPT_DIR / "termin_monitor.py"


CONFIG_FILE = SCRIPT_DIR / "termin_config.json"
DEBUG_DIR = SCRIPT_DIR / "debug"
SRC_MTIME = os.path.getmtime(SOURCE_FILE)
LOG_FILE = SCRIPT_DIR / "termin_monitor.log"
DOCTOLIB_LEDGER_FILE = SCRIPT_DIR / ".doctolib_ledger.json"
DL_PROFILE_DIR = SCRIPT_DIR / ".dl_profile"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
