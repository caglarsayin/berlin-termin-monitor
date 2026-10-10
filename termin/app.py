"""Application flows, worker lifecycle, and signal handling."""

import os
import select
import signal
import subprocess
import sys
import termios
import threading
import tty

from termin.model import Model, booking_url
from termin.providers.berlin import discover
from termin.storage import load_config, save_config, save_selection
from termin.terminal import _read_key
from termin.ui.dashboard import print_summary, render_live, show_logs
from termin.ui.setup import doctolib_welcome, pick_offices, pick_service, welcome_screen
from termin.workers.berlin import monitor_worker
from termin.workers.doctolib import doctolib_worker


def _install_sigint(model):
    """First Ctrl+C stops gracefully, the second force-quits."""
    def on_sigint(_sig, _frame):
        if model.stopping:
            sys.stdout.write("\033[?25h\n\n  bye 👋\n")
            sys.stdout.flush()
            os._exit(130)
        model.stopping = True
    return signal.signal(signal.SIGINT, on_sigint)


def run_live(args, model, worker_fn=None):
    """Action mode: monitoring runs on a worker thread while the keyboard
    drives this screen. Returns "quit" or "back" (to the welcome screen)."""
    worker = threading.Thread(target=worker_fn or monitor_worker,
                              args=(model, args, lambda: None), daemon=True)
    worker.start()
    previous_handler = _install_sigint(model)
    fd = sys.stdin.fileno()
    saved_attrs = termios.tcgetattr(fd)
    sys.stdout.write("\033[?25l")
    leaving = None
    try:
        tty.setcbreak(fd)
        try:
            termios.tcflush(fd, termios.TCIFLUSH)  # drop keys typed between screens
        except termios.error:
            pass
        while not model.stopping and leaving is None:
            render_live(model)
            if not select.select([fd], [], [], 1.0)[0]:
                continue
            k = _read_key()
            o = model.selected()
            if not k:
                continue
            if k in ("up", "k") and model.offices:
                model.cursor = (model.cursor - 1) % len(model.offices)
            elif k in ("down", "j") and model.offices:
                model.cursor = (model.cursor + 1) % len(model.offices)
            elif k in ("enter", "o") and o:
                subprocess.run(["open", booking_url(o)], check=False)
                model.event(f"opened {o['name']} in your browser")
            elif k == " " and o:
                o["paused"] = not o.get("paused")
                model.state[o["name"]]["status"] = "paused" if o["paused"] else "pending"
                model.event(("paused " if o["paused"] else "resumed ") + o["name"])
                save_selection(model)
            elif k == "c":
                if model.checking:
                    model.check_asap = True
                    model.event("manual check queued after this one")
                else:
                    model.next_at = 0
                    model.event("manual check")
            elif k == "l":
                show_logs()
            elif k in ("b", "esc"):
                leaving = "back"
            elif k == "q":
                model.stopping = True
    except KeyboardInterrupt:
        model.stopping = True
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        termios.tcsetattr(fd, termios.TCSADRAIN, saved_attrs)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
    stop_reason = leaving or "quit"
    model.stopping = True
    if model.checking:
        print("\n  finishing the current check …")
    worker.join(timeout=30)
    if stop_reason == "back":
        model.stopping = False
        model.checking = False
        model.next_at = 0
    return stop_reason


def run_headless(args, model, worker_fn=None):
    """--once and piped/cron runs: same worker, no keyboard, frames appended."""
    previous_handler = _install_sigint(model)
    try:
        (worker_fn or monitor_worker)(model, args,
                                      on_update=lambda: render_live(model, live=False))
    finally:
        signal.signal(signal.SIGINT, previous_handler)
    print_summary(model)


def _farewell(model):
    if model is not None and model.cycle:
        print_summary(model)
    else:
        print("\n  bye 👋")


def berlin_flow(args):
    """Berlin mode: welcome screen -> action mode. Returns 'back' or 'quit'."""
    config = {} if args.setup else (load_config() or {})
    if config.get("service_id") and config.get("offices"):
        service_id = config["service_id"]
        service_name, offices = config["service_name"], config["offices"]
    else:
        service_id = pick_service()
        if service_id is None:
            return "back"
        service_name, all_offices = discover(service_id, use_cache=not args.setup)
        offices = pick_offices(all_offices)
        if not offices:
            return "back"
        save_config(service_id, service_name, offices)

    model = Model(service_id, service_name, offices, args.interval)
    while True:
        action = welcome_screen(model, args)
        if action == "back":
            return "back"
        if action == "quit":
            _farewell(model)
            return "quit"
        if run_live(args, model) == "quit":
            _farewell(model)
            return "quit"


def doctolib_flow(args):
    """Doctolib mode: welcome screen -> action mode. Returns 'back' or 'quit'."""
    config = load_config() or {}
    watches = config.get("doctolib") or []
    model = None
    while True:
        action = doctolib_welcome(watches, args)
        if action == "back":
            return "back"
        if not watches:
            continue
        model = Model(None, "Doctolib doctors", watches, args.interval,
                      mode="doctolib")
        if run_live(args, model, doctolib_worker) == "quit":
            _farewell(model)
            return "quit"
