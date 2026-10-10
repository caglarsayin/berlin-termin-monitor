"""Interactive setup screens and command-line selection resolution."""

import sys
import time

from termin.ledger import DL_NEW_SECS, _fmt_date, _fmt_slot
from termin.providers.berlin import KNOWN_SERVICES, discover, normalize, resolve_service
from termin.providers.doctolib import clean_wizard_url, dl_probe, suggest_label
from termin.storage import load_config, load_ledger, save_config, save_doctolib, save_ledger
from termin.terminal import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    IS_TTY,
    MENU_KEYS,
    YELLOW,
    _run_menu,
    ask,
    ask_url,
    c,
    clear_screen,
    menu_header,
)


def print_offices(offices):
    for i, o in enumerate(offices, 1):
        d = f" — {o['district']}" if o["district"] and normalize(o["district"]) not in normalize(o["name"]) else ""
        note = "" if o.get("book") else c(DIM, "   (no online booking — can't monitor)")
        print(f"  {i:2d}. {o['name']}{d}{note}")


def match_offices(offices, specs):
    """Match user specs (district/name substrings, numbers, or 'all')."""
    bookable = [o for o in offices if o.get("book")]
    chosen = []
    for spec in specs:
        s = normalize(spec.strip())
        if not s:
            continue
        if s in ("all", "alle"):
            hits = bookable
        elif s.isdigit() and 1 <= int(s) <= len(offices):
            hits = [offices[int(s) - 1]]
        else:
            hits = [o for o in offices if s in normalize(o["name"] + " " + o["district"])]
        if not hits:
            print(c(YELLOW, f"  ! nothing matched {spec!r}"))
        for o in hits:
            if not o.get("book"):
                print(c(YELLOW, f"  ! {o['name']} has no online booking — skipping"))
            elif o not in chosen:
                chosen.append(o)
    return chosen


def pick_service(current_id=None):
    """Choose the appointment type. Returns a service id, or None on Esc."""
    if not MENU_KEYS:
        return _pick_service_plain(current_id)
    while True:
        entries, default_idx = [], 0
        for i, (sid, label) in enumerate(KNOWN_SERVICES.values()):
            note = c(GREEN, "   ← current") if sid == current_id else ""
            entries.append({"label": label, "value": sid, "note": note})
            if sid == current_id:
                default_idx = i
        entries.append({"label": "Other service…", "value": "other",
                        "note": c(DIM, "   any service.berlin.de ID or URL")})
        clear_screen()
        choice = _run_menu(
            menu_header(c(BOLD, "Appointment type") + c(DIM, " — pick one")),
            entries, default_idx=default_idx)
        if choice != "other":
            return choice
        raw = ask("\n  service.berlin.de ID or URL: ").strip()
        sid = resolve_service(raw) if raw else None
        if sid:
            return sid
        print(c(YELLOW, "  ! couldn't read a service ID from that — back to the list"))
        time.sleep(1.4)


def pick_offices(all_offices, current=None):
    """Choose offices (checkbox list). Returns a list, or None on Esc."""
    if not MENU_KEYS:
        return _pick_offices_plain(all_offices, current)
    current_sids = {o["sid"] for o in (current or [])}
    entries, checked = [], set()
    for i, o in enumerate(all_offices):
        d = (f" — {o['district']}"
             if o["district"] and normalize(o["district"]) not in normalize(o["name"])
             else "")
        if o.get("book"):
            entries.append({"label": o["name"], "value": o, "note": c(DIM, d)})
            if not current or o["sid"] in current_sids:
                checked.add(i)
        else:
            entries.append({"label": o["name"], "value": o, "disabled": True,
                            "note": d + "  (no online booking)"})
    clear_screen()
    return _run_menu(
        menu_header(c(BOLD, "Offices") + c(DIM, " — pick as many as you like")),
        entries, multi=True, checked=checked)


def _pick_service_plain(current_id=None):
    print(c(BOLD, "\n  Appointment type") + c(DIM, "  (pick one)\n"))
    aliases = list(KNOWN_SERVICES)
    for i, a in enumerate(aliases, 1):
        sid, label = KNOWN_SERVICES[a]
        marker = c(GREEN, " ← current") if sid == current_id else ""
        print(f"  {i}. {label}{marker}")
    print(c(DIM, "  …or paste any service.berlin.de Dienstleistung ID or URL"))
    while True:
        default = " [Enter = keep current]" if current_id else ""
        raw = ask(f"\n  Choice{default}: ").strip()
        if not raw and current_id:
            return current_id
        if raw.isdigit() and 1 <= int(raw) <= len(aliases):
            return KNOWN_SERVICES[aliases[int(raw) - 1]][0]
        sid = resolve_service(raw)
        if sid:
            return sid
        print(c(YELLOW, "  ! not a catalog number, alias, ID, or URL — try again"))


def _pick_offices_plain(all_offices, current=None):
    print(c(BOLD, "\n  Offices") + c(DIM, "  (pick as many as you like)\n"))
    print_offices(all_offices)
    default_label = (", ".join(o["name"] for o in current) if current
                     else "all bookable offices")
    while True:
        raw = ask(f'\n  Numbers/names/"all" [Enter = {default_label}]: ').strip()
        if not raw:
            chosen = current or [o for o in all_offices if o.get("book")]
        else:
            chosen = match_offices(all_offices, raw.split(","))
        if chosen:
            return chosen
        print(c(YELLOW, "  ! nothing selected — try again"))


def dl_add_watch(watches):
    raw = ask_url("\n  Paste the Doctolib booking URL (from your browser): ")
    if not raw:
        return
    if "doctolib." not in raw:
        print(c(YELLOW, "  ! that doesn't look like a doctolib.de URL"))
        time.sleep(1.4)
        return
    url = clean_wizard_url(raw)
    suggestion = suggest_label(url)
    label = ask(f"  Label [{suggestion}]: ").strip() or suggestion
    if any(x in label for x in ("http", "&", "=")):  # stray paste remnants
        label = suggestion
    print(c(DIM, "  running a first check (opens the page headlessly) …"), flush=True)
    try:
        feed, slots, nxt = dl_probe(url)
    except Exception as e:
        print(c(YELLOW, f"  ! first check failed ({str(e).splitlines()[0][:60]})"))
        feed, slots, nxt = None, [], None
    if feed and slots:
        days = len({s[:10] for s in slots})
        print(c(GREEN, f"  ✓ feed captured — {len(slots)} slot(s) across {days} day(s), "
                       f"earliest {_fmt_slot(min(slots))}"))
    elif feed:
        hint = f", next known: {_fmt_date(nxt)}" if nxt else ""
        print(c(GREEN, "  ✓ feed captured — currently no free slots" + hint))
    else:
        print(c(YELLOW, "  ! couldn't capture the availability feed — saving anyway, "
                        "the monitor will keep trying"))
    watch = {"name": label, "book": url, "feed": feed, "paused": False,
             "sid": f"dl{abs(hash(url)) % 10**8}"}
    if feed is not None:
        # Existing slots form a silent baseline; only later additions alert.
        now = time.time()
        ledger = load_ledger()
        led = ledger.setdefault(url, {})
        for k in slots:
            led.setdefault(k, {"first": now - DL_NEW_SECS, "gone": None})
        save_ledger(ledger)
        watch["seeded"] = True
    watches.append(watch)
    save_doctolib(watches)
    ask(c(DIM, "  [Enter] continue "))


def dl_remove_watch(watches):
    if not watches:
        return
    entries = [{"label": w["name"], "value": i} for i, w in enumerate(watches)]
    if MENU_KEYS:
        clear_screen()
        idx = _run_menu(menu_header(c(BOLD, "Remove which doctor?")), entries)
    else:
        print_offices_plain = "\n".join(f"  {i + 1}. {w['name']}" for i, w in enumerate(watches))
        print("\n" + print_offices_plain)
        raw = ask("  Remove which number (Enter = cancel)? ").strip()
        idx = int(raw) - 1 if raw.isdigit() and 1 <= int(raw) <= len(watches) else None
    if idx is not None:
        gone = watches.pop(idx)
        save_doctolib(watches)
        print(c(DIM, f"  removed {gone['name']}"))
        time.sleep(0.8)


def doctolib_welcome(watches, args):
    """Doctolib home screen. Returns 'start' or 'back'."""
    while True:
        clear_screen()
        print("\n" + c(BOLD + CYAN, "  ══ Berlin Termin Monitor · Doctolib ══") + "\n")
        if watches:
            print("  Watching:")
            for w in watches:
                flag = c(DIM, "  (paused)") if w.get("paused") else ""
                ok = "" if w.get("feed") else c(YELLOW, "  (feed pending)")
                print(f"    • {c(BOLD, w['name'])}{flag}{ok}")
        else:
            print(c(DIM, "  No doctors yet — add one with the URL of their booking page."))
        print()

        entries = []
        if watches:
            entries.append({"label": "Start monitoring", "value": "start",
                            "note": c(DIM, "   chimes when a new bookable day appears")})
        entries.append({"label": "Add a doctor", "value": "add"})
        if watches:
            entries.append({"label": "Remove a doctor", "value": "remove"})
        entries.append({"label": "Back", "value": "back"})

        if MENU_KEYS:
            action = _run_menu([], entries) or "back"
        else:
            typed = ask("  [Enter] start   [a]dd   [r]emove   [b]ack : ").strip().lower()
            action = {"": "start" if watches else "add", "a": "add",
                      "r": "remove", "b": "back"}.get(typed, "back")

        if action in ("start", "back"):
            return action
        if action == "add":
            dl_add_watch(watches)
        elif action == "remove":
            dl_remove_watch(watches)


def mode_select(default_mode):
    """First screen: what are we tracking? Returns 'berlin'/'doctolib'/None."""
    entries = [
        {"label": "Berlin public services", "value": "berlin",
         "note": c(DIM, "   Bürgeramt, VHS, Einbürgerungstest …")},
        {"label": "Doctolib doctors", "value": "doctolib",
         "note": c(DIM, "   any doctor's booking page")},
        {"label": "Quit", "value": "quit"},
    ]
    default_idx = 1 if default_mode == "doctolib" else 0
    if MENU_KEYS:
        clear_screen()
        choice = _run_menu(menu_header(c(BOLD, "What are you tracking?")),
                           entries, default_idx=default_idx)
        return None if choice in (None, "quit") else choice
    typed = ask("\n  Track [b]erlin services or [d]octolib doctors ([q]uit)? ").strip().lower()
    return {"b": "berlin", "d": "doctolib", "": default_mode}.get(typed)


def configure(args):
    """Work out (service_id, service_name, offices) from flags, saved config,
    or the interactive start screen."""
    config = load_config()

    if args.service or args.offices or args.list_offices:
        if args.service:
            service_id = resolve_service(args.service)
            if not service_id:
                sys.exit(f"Unknown service {args.service!r}. Use --list-services, "
                         f"a numeric ID, or a service.berlin.de URL.")
        elif config:
            service_id = config["service_id"]
        else:
            sys.exit("Pass --service too (no saved selection yet).")

        service_name, all_offices = discover(service_id, use_cache=not args.setup)
        if args.list_offices:
            print(f"\n{service_name} — offices:")
            print_offices(all_offices)
            sys.exit(0)
        if args.offices:
            chosen = match_offices(all_offices, args.offices)
        elif config and config["service_id"] == service_id:
            chosen = config["offices"]
        else:
            chosen = [o for o in all_offices if o.get("book")]
        if not chosen:
            sys.exit("No monitorable offices selected.")
        save_config(service_id, service_name, chosen)
        return service_id, service_name, chosen

    if args.setup and IS_TTY:
        config = None
    if config:
        return config["service_id"], config["service_name"], config["offices"]
    if not IS_TTY:
        sys.exit("No saved config. Run interactively once, or pass --service/--offices.")

    service_id = pick_service()
    if service_id is None:
        print("\n  bye 👋")
        sys.exit(0)
    service_name, all_offices = discover(service_id, use_cache=not args.setup)
    offices = pick_offices(all_offices)
    if not offices:
        print("\n  bye 👋")
        sys.exit(0)
    save_config(service_id, service_name, offices)
    return service_id, service_name, offices


def _change_offices(model, args):
    _, all_offices = discover(model.service_id)
    chosen = pick_offices(all_offices, current=model.offices)
    if not chosen:
        return
    paused_sids = {o["sid"] for o in model.offices if o.get("paused")}
    for o in chosen:
        o["paused"] = o["sid"] in paused_sids
    model.offices = chosen
    model.cursor = min(model.cursor, len(chosen) - 1)
    model.reset_rows()
    save_config(model.service_id, model.service_name, model.offices)
    model.event("office selection updated")


def _change_service(model, args):
    new_id = pick_service(model.service_id)
    if new_id is None or new_id == model.service_id:
        return
    service_name, all_offices = discover(new_id)
    chosen = pick_offices(all_offices)
    if not chosen:  # Esc = abandon the service change
        return
    model.service_id, model.service_name = new_id, service_name
    model.offices = chosen
    model.cursor = 0
    model.state = {}
    model.reset_rows()
    model.next_at = 0
    save_config(new_id, service_name, chosen)
    model.event(f"now watching: {service_name}")


def welcome_screen(model, args):
    """Home screen: review the configuration, then enter action mode.
    Returns "start" or "quit"."""
    while True:
        clear_screen()
        print("\n" + c(BOLD + CYAN, "  ══ Berlin Termin Monitor ══") + "\n")
        print(f"  Appointment : {c(BOLD, model.service_name)}")
        offices_line = " · ".join(
            o["name"] + (c(DIM, " (paused)") if o.get("paused") else "")
            for o in model.offices)
        print(f"  Offices     : {c(BOLD, offices_line)}")
        print(c(DIM, f"  Checks      : every ~{model.interval}s"))
        print()

        if MENU_KEYS:
            action = _run_menu([], [
                {"label": "Start monitoring", "value": "start",
                 "note": c(DIM, "   chimes when a new slot appears")},
                {"label": "Change appointment type", "value": "service"},
                {"label": "Change offices", "value": "offices"},
                {"label": "Back", "value": "back"},
                {"label": "Quit", "value": "quit"},
            ]) or "back"
        else:
            typed = ask("  " + c(GREEN, "[Enter]") + " start   [a]ppointment   "
                        + "[o]ffices   [b]ack   [q]uit : ").strip().lower()
            action = {"": "start", "a": "service", "o": "offices",
                      "b": "back", "q": "quit"}.get(typed, "")

        if action in ("start", "quit", "back"):
            return action
        if action == "service":
            _change_service(model, args)
        elif action == "offices":
            _change_offices(model, args)
