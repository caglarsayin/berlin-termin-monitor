"""Optional live settings from Home Assistant.

When TERMIN_HA_URL and TERMIN_HA_TOKEN are set, the Doctolib worker reads its
settings from Home Assistant before each check instead of command-line flags:

  input_datetime.termin_from / termin_to   time window (HH:MM:SS states)
  input_number.termin_days                 look-ahead in days
  input_boolean.termin_enabled             pause / resume monitoring
  input_button.termin_check_now            press = check immediately
  todo.termin_doctors                      open items = watched doctors

A to-do item whose name is a pasted Doctolib URL is tidied up: it is renamed
to the doctor's label and the cleaned URL is moved to the item description.
Entity ids can be overridden with TERMIN_HA_ENTITY_<KEY> (e.g. ..._DOCTORS).
"""

import json
import os
import urllib.error
import urllib.request

from termin.diagnostics import log_debug
from termin.providers.doctolib import clean_wizard_url, suggest_label

TIMEOUT = 15
DEFAULT_ENTITIES = {
    "from": "input_datetime.termin_from",
    "to": "input_datetime.termin_to",
    "days": "input_number.termin_days",
    "enabled": "input_boolean.termin_enabled",
    "check_now": "input_button.termin_check_now",
    "doctors": "todo.termin_doctors",
}


def _entity(key):
    return os.environ.get(f"TERMIN_HA_ENTITY_{key.upper()}", DEFAULT_ENTITIES[key])


def enabled():
    return bool(os.environ.get("TERMIN_HA_URL") and os.environ.get("TERMIN_HA_TOKEN"))


def _call(method, path, body=None):
    base = os.environ["TERMIN_HA_URL"].rstrip("/")
    req = urllib.request.Request(
        base + path, method=method,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {os.environ['TERMIN_HA_TOKEN']}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def _state(key):
    return _call("GET", f"/api/states/{_entity(key)}")


def _hhmm(state):
    value = (state or {}).get("state", "")
    return value[:5] if len(value) >= 5 and value[2] == ":" else None


def _doctor_items():
    resp = _call("POST", "/api/services/todo/get_items?return_response",
                 {"entity_id": _entity("doctors"), "status": "needs_action"})
    service_response = (resp or {}).get("service_response", {})
    return service_response.get(_entity("doctors"), {}).get("items", [])


def _doctor_from_item(item):
    """Return (label, url) for a to-do item, tidying pasted-URL items in HA."""
    summary = (item.get("summary") or "").strip()
    description = (item.get("description") or "").strip()
    if "doctolib." in description:
        return summary or suggest_label(clean_wizard_url(description)), clean_wizard_url(description)
    if "doctolib." not in summary:
        return None
    url = clean_wizard_url(summary)
    label = suggest_label(url)
    try:
        _call("POST", "/api/services/todo/update_item",
              {"entity_id": _entity("doctors"), "item": item["uid"], "rename": label, "description": url})
        log_debug(f"remote: tidied doctor item → {label}")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        log_debug(f"remote: could not tidy doctor item: {e!r}")
    return label, url


def fetch_settings():
    """Read all settings from HA. Returns a dict, or None if HA is unreachable."""
    try:
        start, end = _hhmm(_state("from")), _hhmm(_state("to"))
        days_state = _state("days").get("state")
        days = int(float(days_state)) if days_state not in (None, "unknown", "unavailable") else None
        is_on = _state("enabled").get("state") != "off"
        pressed = _state("check_now").get("state")
        doctors = [d for d in (_doctor_from_item(i) for i in _doctor_items()) if d]
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        log_debug(f"remote: settings unavailable ({e!r}) — keeping previous settings")
        return None
    between = (start, end) if start and end and start <= end else None
    return {"between": between, "days": days, "enabled": is_on,
            "check_now": pressed, "doctors": doctors}


def check_now_marker():
    """Last-pressed timestamp of the check-now button, or None."""
    try:
        return _state("check_now").get("state")
    except (urllib.error.URLError, OSError, ValueError, KeyError, AttributeError):
        return None


def sync_watches(watches, doctors):
    """Make `watches` (list of dicts, mutated in place) match the HA doctor list.

    Existing watches keep their feed/seeded state (matched by URL); new doctors
    start unseeded so their first poll is a silent baseline. Returns True when
    the list changed."""
    by_url = {w["book"]: w for w in watches}
    wanted = []
    for label, url in doctors:
        w = by_url.get(url) or {"name": label, "book": url, "feed": None, "paused": False,
                                "sid": f"dl{abs(hash(url)) % 10**8}"}
        w["name"] = label
        wanted.append(w)
    names = [w["name"] for w in wanted]
    for i, w in enumerate(wanted):  # keep row names unique for the dashboard state
        if names.count(w["name"]) > 1:
            w["name"] = f"{w['name']} ({i + 1})"
    changed = [w["book"] for w in watches] != [w["book"] for w in wanted] or \
        [w["name"] for w in watches] != [w["name"] for w in wanted]
    watches[:] = wanted
    return changed
