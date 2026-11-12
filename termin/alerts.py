"""Alert delivery: macOS sound/notification, or an HTTP webhook when configured.

Set TERMIN_WEBHOOK_URL (e.g. a Home Assistant webhook) to receive alerts and
per-check status updates as JSON POSTs. Without it, alerts use macOS only.
"""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

from termin.diagnostics import log_debug


DEFAULT_SOUND = "/System/Library/Sounds/Hero.aiff"
WEBHOOK_TIMEOUT = 10


def _webhook_url():
    return os.environ.get("TERMIN_WEBHOOK_URL", "").strip() or None


def post_webhook(payload):
    """POST payload as JSON to TERMIN_WEBHOOK_URL. Never raises; returns success."""
    url = _webhook_url()
    if not url:
        return False
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError) as e:
        log_debug(f"webhook {payload.get('event')} failed: {e!r}")
        return False


def play_sound(path, times=1):
    if not shutil.which("afplay"):
        return
    for _ in range(times):
        subprocess.run(["afplay", path], check=False)


def notify(title, message, url=None):
    post_webhook({"event": "alert", "title": title, "message": message, "url": url})
    if shutil.which("osascript"):
        # Text goes in as argv, never into the script source (no AppleScript injection).
        subprocess.run(["osascript",
                        "-e", "on run argv",
                        "-e", 'display notification (item 1 of argv) with title (item 2 of argv) sound name "Hero"',
                        "-e", "end run", str(message), str(title)], check=False)


def report_status(name, state):
    """Send one watch's post-check state (no-op without a webhook)."""
    post_webhook({
        "event": "status",
        "name": name,
        "status": state.get("status"),
        "summary": state.get("summary") or "",
        "next": state.get("next"),
        "dates": state.get("dates") or [],
        "reason": state.get("reason"),
        "checked": state.get("checked"),
    })
