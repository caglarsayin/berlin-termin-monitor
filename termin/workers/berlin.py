"""Berlin polling, recovery, and alert scheduling."""

import os
import random
import subprocess
import time
import traceback
from datetime import datetime

from termin.alerts import notify, play_sound
from termin.diagnostics import log_debug
from termin.model import booking_url
from termin.paths import SOURCE_FILE, SRC_MTIME
from termin.providers.berlin import check_location
from termin.terminal import BOLD, GREEN, RED, YELLOW


def monitor_worker(model, args, on_update):
    """Run check cycles until model.stopping. All Playwright use lives here,
    so in live mode this runs on a background thread and the keyboard stays
    responsive."""
    from playwright.sync_api import sync_playwright, Error as PlaywrightError

    try:
        with sync_playwright() as p:
            browser = None
            try:
                while not model.stopping:
                    if time.time() < model.next_at:
                        time.sleep(0.2)
                        continue
                    model.checking = True
                    model.cycle += 1
                    if not model.stale and os.path.getmtime(SOURCE_FILE) != SRC_MTIME:
                        model.stale = True
                        model.event("code updated on disk — restart to apply", YELLOW)
                    throttled = False
                    try:
                        if browser is None or not browser.is_connected():
                            browser = p.chromium.launch(channel="chrome", headless=True)

                        for o in list(model.offices):
                            if model.stopping:
                                break
                            st = model.state.get(o["name"])
                            if st is None:  # removed while we were checking
                                continue
                            if o.get("paused"):
                                st["status"] = "paused"
                                continue
                            prev_status = st["status"]
                            st["status"] = "checking"
                            on_update()
                            try:
                                dates, status = check_location(browser, booking_url(o))
                            except PlaywrightError as e:
                                st["status"] = "error"
                                model.event(f"{o['name']}: browser error, retrying "
                                            f"({str(e).splitlines()[0][:60]})", YELLOW)
                                try:
                                    browser.close()
                                except Exception:
                                    pass
                                browser = None
                                break

                            now = datetime.now().strftime("%H:%M:%S")
                            st["checked"] = now
                            prev = set(st["dates"])

                            if status == "throttled":
                                st["status"] = "throttled"
                                throttled = True
                                model.event(f"{o['name']}: rate-limited, doubling the wait", YELLOW)
                            elif status == "blocked":
                                st["status"] = "blocked"
                                model.event(f"{o['name']}: stuck on the access check", RED)
                            elif dates:
                                st["status"] = "available"
                                st["dates"] = dates
                                st["found_at"] = st["found_at"] or now
                                new = sorted(set(dates) - prev)
                                gone = sorted(prev - set(dates))
                                if new:
                                    model.event(f"🚨 {o['name']}: NEW slot {', '.join(new)}",
                                                BOLD + GREEN)
                                    notify(f"Slot: {model.service_name}",
                                           f"{o['name']}: {', '.join(new)}")
                                    if args.open:
                                        subprocess.run(["open", booking_url(o)], check=False)
                                    on_update()
                                    play_sound(args.sound, times=3)
                                elif gone:
                                    model.event(f"{o['name']}: {', '.join(gone)} taken", YELLOW)
                            else:
                                st["status"] = "none"
                                if prev:
                                    model.event(f"{o['name']}: slots gone "
                                                f"({', '.join(sorted(prev))} taken)", YELLOW)
                                    st["found_at"] = None
                                st["dates"] = []
                            if (prev_status in ("error", "blocked", "throttled")
                                    and st["status"] in ("available", "none")):
                                model.event(f"✓ {o['name']}: recovered", GREEN)
                                log_debug(f"{o['name']}: recovered")
                            on_update()
                    except Exception as e:
                        model.event(f"unexpected error: {e!r} — continuing", RED)
                        log_debug("cycle error:\n" + traceback.format_exc())
                        on_update()

                    delay = args.interval + random.randint(0, 30)
                    if throttled:
                        delay *= 2
                    model.next_at = 0 if model.check_asap else time.time() + delay
                    model.check_asap = False
                    model.checking = False
                    if args.once:
                        break
            finally:
                model.checking = False
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass
    except Exception:
        pass  # Ignore Playwright teardown errors after interruption.
