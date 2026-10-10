"""Dashboard, slot-panel, diagnostics, and session-summary rendering."""

import sys
import time
from datetime import datetime

from termin.ledger import DL_NEW_SECS
from termin.paths import LOG_FILE
from termin.terminal import (
    BLUE,
    BOLD,
    CYAN,
    DIM,
    GRAY,
    GREEN,
    IS_TTY,
    RED,
    STRIKE,
    YELLOW,
    _read_key,
    c,
    clear_screen,
)


def _log_color(line):
    low = line.lower()
    if "recovered" in low or "new day" in low or "🚨" in line:
        return BOLD + GREEN
    if "slot(s) in" in low or "started" in low:
        return GREEN
    if ("failed" in low or "429" in low or "403" in low or "error" in low
            or "traceback" in low):
        return RED
    if any(k in low for k in ("backing off", "retrying", "no usable", "deflection",
                              "flagged", "wiping", "quiet hours", "resuming",
                              "stale", "profile in use", "evidence")):
        return YELLOW
    if "cycle " in low:
        return DIM
    return ""


def show_logs():
    """Full-screen log tail, color-coded; any key returns."""
    clear_screen()
    print("\n" + c(BOLD + CYAN, "  ── diagnostics ── ") + c(DIM, str(LOG_FILE))
          + "\n  " + c(GREEN, "success") + c(DIM, " · ") + c(YELLOW, "warning")
          + c(DIM, " · ") + c(RED, "failure") + c(DIM, " · health") + "\n")
    try:
        lines = LOG_FILE.read_text().splitlines()[-30:]
    except OSError:
        lines = []
    for line in lines or ["(no log entries yet)"]:
        color = _log_color(line)
        print("  " + (c(color, line[:112]) if color else line[:112]))
    print(c(DIM, "\n  [any key] back"))
    _read_key()


STATUS_ICON = {
    "available": "🟢",
    "none":      "⚪",
    "checking":  "🔎",
    "throttled": "🟡",
    "blocked":   "🔴",
    "error":     "🔴",
    "paused":    "◌ ",
    "pending":   "… ",
}


def _row_status(st):
    s = st["status"]
    if s == "available":
        if st.get("summary"):  # doctolib rows aggregate instead of listing dates
            return c(BOLD + GREEN, st["summary"])
        return c(BOLD + GREEN, "   ".join(st["dates"]))
    if s == "none":
        hint = f" (next: {st['next']})" if st.get("next") else ""
        return c(DIM, "no slots" + hint)
    if s == "checking":
        return c(CYAN, "checking…")
    if s == "paused":
        return c(DIM, "paused")
    if s == "throttled":
        return c(YELLOW, "rate-limited")
    if s in ("blocked", "error"):
        detail = st.get("reason") or "check failed"
        since = f" since {st['fail_since']}" if st.get("fail_since") else ""
        return c(RED, detail + since)
    return c(DIM, "waiting")


def render_live(model, live=True):
    lines = ["", c(BOLD + CYAN, "  ══ Berlin Termin Monitor ══")]
    lines.append("  " + c(BOLD, model.service_name)
                 + c(DIM, f"   check #{model.cycle} · every ~{model.interval}s")
                 + (c(YELLOW, "   ⟳ update on disk — restart to apply")
                    if model.stale else ""))
    lines.append("")

    width = min(max((len(o["name"]) for o in model.offices), default=20), 44)
    for i, o in enumerate(model.offices):
        st = model.state.get(o["name"])
        if st is None:
            continue
        sel = live and i == model.cursor
        pointer = c(GREEN, "▶") if sel else " "
        icon = STATUS_ICON[st["status"]]
        name = f"{o['name'][:width]:<{width}}"
        if sel:
            name = c(BOLD + CYAN, name)
        checked = c(DIM, st["checked"] or "")
        lines.append(f"  {pointer} {icon} {name}  {_row_status(st)}  {checked}")
    lines.append("")

    if live:
        # Reserve a line so selection changes do not shift the layout.
        url = ""
        sel_office = model.selected()
        if sel_office:
            st = model.state.get(sel_office["name"])
            url = st["url"] if st else ""
        short = url.replace("https://", "")
        if len(short) > 72:
            short = short[:71] + "…"
        lines.append("  🔗 " + c(DIM, short or "—"))
        lines.append("")

    if getattr(model, "mode", "berlin") == "doctolib":
        lines.extend(_dl_panel_lines(model, live))
        lines.append("")

    # Pad events to keep the footer in place.
    shown = list(model.events)[:5]
    for ts, msg, color in shown:
        lines.append(f"  {c(DIM, ts)}  {c(color, msg) if color else msg}")
    if live:
        lines.extend([""] * (5 - len(shown)))
    lines.append("")

    lines.append(c(DIM, "  " + "─" * 50))
    legend = ""
    if getattr(model, "mode", "berlin") == "doctolib":
        legend = ("        " + c(BOLD + BLUE, "new") + c(DIM, " · known · ")
                  + c(GRAY + STRIKE, "taken"))
    if model.stopping:
        lines.append(c(YELLOW, "  stopping — finishing the current check "
                              "(Ctrl+C again to force quit)"))
    elif model.checking:
        lines.append(c(CYAN, "  checking…") + legend)
    else:
        left = max(0, int(model.next_at - time.time()))
        lines.append(c(DIM, f"  next check in {left // 60}:{left % 60:02d}") + legend)
    if live:
        lines.append(c(DIM, "  [o] open in browser   [space] pause   [c] check now"))
        lines.append(c(DIM, "  [b] back to setup     [l] logs        [q] quit"))
    else:
        lines.append(c(DIM, "  Ctrl+C stops"))

    frame = "\n".join(lines)
    if IS_TTY:
        clear_screen()
        sys.stdout.write(frame + "\n")
    else:
        sys.stdout.write("\n" + frame + "\n")
    sys.stdout.flush()


def print_summary(model):
    mins, secs = divmod(int((datetime.now() - model.started).total_seconds()), 60)
    hours, mins = divmod(mins, 60)
    dur = (f"{hours}h {mins}m" if hours else f"{mins}m {secs}s")
    print("\n\n" + c(DIM, "  ── session summary ─────────────────────"))
    print(f"  {model.service_name}")
    print(c(DIM, f"  {model.cycle} check(s) over {dur}"))
    for o in model.offices:
        st = model.state.get(o["name"])
        if st is None:
            continue
        if o.get("paused"):
            print(f"  ◌  {o['name']} — " + c(DIM, "paused"))
        elif st["dates"]:
            print(f"  🟢 {o['name']} — last seen "
                  + c(BOLD + GREEN, "AVAILABLE: " + ", ".join(st["dates"])))
            print(f"      book → {st['url']}")
        else:
            print(f"  ⚪ {o['name']} — " + c(DIM, "no slots while watching"))
    print("\n  bye 👋")


DL_PANEL_DAYS = 8


def _dl_panel_lines(model, live):
    """Doctolib slot panel: fixed height, day rows with color-coded times."""
    o = model.selected() if live else (model.offices[0] if model.offices else None)
    st = model.state.get(o["name"]) if o else None
    led = (st or {}).get("ledger") or {}
    now = time.time()

    by_day = {}
    for key in sorted(led):
        v = led[key]
        status = ("gone" if v.get("gone")
                  else "new" if now - v.get("first", 0) < DL_NEW_SECS
                  else "known")
        by_day.setdefault(key[:10], []).append((key[11:16], status))

    name = (o["name"] if o else "")[:40]
    lines = [c(DIM, f"  ── {name} " + "─" * max(0, 46 - len(name)))]
    day_rows = []
    for date, chips in by_day.items():
        try:
            label = datetime.strptime(date, "%Y-%m-%d").strftime("%a %d %b")
        except ValueError:
            label = date
        parts = []
        for tm, status in chips:
            if status == "new":
                parts.append(c(BOLD + BLUE, tm))
            elif status == "gone":
                parts.append(c(GRAY + STRIKE, tm))
            else:
                parts.append(tm)
        day_rows.append(f"  {label:<12} " + "  ".join(parts))

    if not day_rows:
        hint = f"next known slot: {st['next']}" if st and st.get("next") else "no upcoming slots"
        day_rows = [c(DIM, "  " + hint)]
    if len(day_rows) > DL_PANEL_DAYS:
        day_rows = day_rows[:DL_PANEL_DAYS - 1] + [
            c(DIM, f"  … +{len(day_rows) - (DL_PANEL_DAYS - 1)} more days")]
    day_rows += [""] * (DL_PANEL_DAYS - len(day_rows))
    return lines + day_rows
