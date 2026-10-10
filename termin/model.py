"""Shared dashboard state and booking-link access."""

from collections import deque
from datetime import datetime


class Model:
    """State shared between the UI thread and the checker thread.

    The checker thread only mutates row/state fields and timestamps; the UI
    thread reads them and edits the office list. CPython's atomic dict/list
    operations are sufficient here — no lock needed.
    """

    def __init__(self, service_id, service_name, offices, interval, mode="berlin"):
        self.service_id = service_id
        self.service_name = service_name
        self.interval = interval
        self.mode = mode  # "berlin" or "doctolib"; offices double as watches
        self.offices = offices
        self.state = {}
        self.reset_rows()
        self.events = deque(maxlen=8)
        self.cycle = 0
        self.cursor = 0
        self.started = datetime.now()
        self.checking = False
        self.check_asap = False
        self.stopping = False
        self.stale = False
        self.next_at = 0.0  # epoch seconds; 0 = check as soon as possible

    def reset_rows(self):
        old = self.state
        self.state = {}
        for o in self.offices:
            self.state[o["name"]] = old.get(o["name"]) or {
                "status": "paused" if o.get("paused") else "pending",
                "dates": [], "checked": None, "found_at": None,
                "url": booking_url(o)}

    def event(self, msg, color=""):
        if len(msg) > 100:
            msg = msg[:99] + "…"
        self.events.appendleft((datetime.now().strftime("%H:%M:%S"), msg, color))

    def selected(self):
        return self.offices[self.cursor] if self.offices else None


def booking_url(office):
    return office["book"]
