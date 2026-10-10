"""Bounded diagnostic logging shared by both providers."""

import threading
from datetime import datetime

from termin.paths import LOG_FILE


_log_lock = threading.Lock()


def log_debug(msg):
    """Append a diagnostic line; view with the 'l' key in action mode."""
    line = f"{datetime.now():%d.%m %H:%M:%S}  {msg}\n"
    with _log_lock:
        try:
            existing = LOG_FILE.read_text() if LOG_FILE.exists() else ""
            lines = (existing + line).splitlines(keepends=True)
            if len(lines) > 500:
                lines = lines[-300:]
            LOG_FILE.write_text("".join(lines))
        except OSError:
            pass
