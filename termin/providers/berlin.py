"""Berlin service discovery and calendar scraping."""

import json
import random
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from termin.paths import SCRIPT_DIR, UA
from termin.storage import _upgrade_office
from termin.terminal import DIM, YELLOW, c


KNOWN_SERVICES = {
    "citizenship-test":    (351180, "Citizenship test registration (Einbürgerungstest)"),
    "register-address":    (120686, "Register your address (Anmeldung)"),
    "deregister-address":  (120335, "Deregister a residence (Abmeldung)"),
    "id-card":             (120703, "German ID card (Personalausweis)"),
    "passport":            (121151, "German passport (Reisepass)"),
    "collect-id":          (324325, "Collect a finished ID card (Personalausweis abholen)"),
    "collect-passport":    (324573, "Collect a finished passport (Reisepass abholen)"),
    "registration-cert":   (120702, "Registration certificate (Meldebescheinigung)"),
    "police-clearance":    (120926, "Police clearance certificate (Führungszeugnis)"),
    "certified-copies":    (121701, "Certified copies (Beglaubigung von Kopien)"),
    "visa-invitation":     (326540, "Visa invitation letter (Verpflichtungserklärung)"),
    "register-business":   (121921, "Register a business (Gewerbeanmeldung)"),
    "residents-parking":   (121721, "Resident parking permit (Bewohnerparkausweis)"),
    "intl-driving-permit": (121591, "International driving permit (Internationaler Führerschein)"),
    "licence-conversion":  (327537, "Convert a non-EU driving licence (Umschreibung)"),
    "licence-exchange":    (124556, "Exchange old licence for EU card (Führerschein-Umtausch)"),
    "housing-certificate": (120671, "Housing entitlement certificate (WBS)"),
}


SERVICE_ALIASES = {
    "einbuergerungstest": 351180, "anmeldung": 120686, "abmeldung": 120335,
    "personalausweis": 120703, "reisepass": 121151, "meldebescheinigung": 120702,
    "fuehrerschein-umschreibung": 327537,
}


BOOKABLE_RE = re.compile(
    r'aria-label="(\d{2}\.\d{2}\.\d{4}) - An diesem Tag einen Termin buchen"'
)


NEXT_MONTH_RE = re.compile(
    r'<a[^>]*aria-label="zu nächstem Monat[^"]*"[^>]*'
    r'href="(/terminvereinbarung/termin/day/\d+/)"'
    r'|<a[^>]*href="(/terminvereinbarung/termin/day/\d+/)"[^>]*'
    r'aria-label="zu nächstem Monat[^"]*"'
)


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def strip_tags(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def normalize(s):
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return s


def resolve_service(spec):
    """Accept a catalog alias, a numeric ID, or a /dienstleistung/<id>/ URL."""
    spec = spec.strip()
    key = normalize(spec).replace(" ", "-")
    if key in KNOWN_SERVICES:
        return KNOWN_SERVICES[key][0]
    if key in SERVICE_ALIASES:
        return SERVICE_ALIASES[key]
    m = re.search(r"dienstleistung/(\d+)", spec)
    if m:
        return int(m.group(1))
    if spec.isdigit():
        return int(spec)
    return None


def fetch_office(service_id, sid):
    html = http_get(f"https://service.berlin.de/dienstleistung/{service_id}/standort/{sid}/")
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    text = strip_tags(h1.group(1)) if h1 else ""
    name = text.split(" am Standort ", 1)[1] if " am Standort " in text else text
    district = ""
    m = re.search(r"Bezirksamt\s+([A-Za-zÄÖÜäöüß\- ]{2,40})", html)
    if m:
        district = m.group(1).replace("von Berlin", "").strip().rstrip("-").strip()
    # Online booking comes in two flavours: VHS-style tag.php deep links and
    # Bürgeramt-style /termin/provider/<office>/<service>/ links.
    book = None
    tag = re.search(r"tag\.php\?id=(\d+)", html)
    if tag:
        book = (f"https://service.berlin.de/terminvereinbarung/termin/tag.php"
                f"?id={tag.group(1)}&anliegen[]={service_id}")
    elif re.search(rf"termin/provider/{sid}/{service_id}/", html):
        book = f"https://service.berlin.de/terminvereinbarung/termin/provider/{sid}/{service_id}/"
    return {"sid": sid, "name": name or f"Standort {sid}",
            "district": district, "tag": int(tag.group(1)) if tag else None,
            "book": book, "service_id": service_id}


def discover(service_id, use_cache=True):
    """Return (service_name, [office, ...]) for a Dienstleistung, cached 7 days."""
    cache_file = SCRIPT_DIR / f".offices_{service_id}.json"
    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text())
        # Invalidate caches built with an older discovery parser.
        if (cached.get("v") == 2
                and datetime.fromisoformat(cached["fetched"]) > datetime.now() - timedelta(days=7)):
            for o in cached["offices"]:
                _upgrade_office(o, service_id)
            return cached["service"], cached["offices"]

    print(c(DIM, "  looking up offices on service.berlin.de …"), flush=True)
    html = http_get(f"https://service.berlin.de/dienstleistung/{service_id}/")
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    service_name = strip_tags(title.group(1)).split(" - Dienstleistungen")[0] if title else str(service_id)
    sids = list(dict.fromkeys(re.findall(rf"/dienstleistung/{service_id}/standort/(\d+)/", html)))
    if not sids:
        sys.exit(f"No offices found for service {service_id} — check the ID on service.berlin.de.")

    def fetch_with_retry(s):
        for pause in (0, 2, 5):
            time.sleep(pause + random.uniform(0, 0.4))
            try:
                return fetch_office(service_id, s)
            except Exception:
                pass
        return None  # one unreadable office page shouldn't kill discovery

    with ThreadPoolExecutor(max_workers=3) as pool:
        offices = [o for o in pool.map(fetch_with_retry, sids) if o]
    failed = len(sids) - len(offices)
    if failed:
        print(c(YELLOW, f"  ! {failed} office page(s) could not be read — continuing without them"))
    if not offices:
        sys.exit(f"Could not read any office pages for service {service_id} — try again later.")
    offices.sort(key=lambda o: (o["book"] is None, normalize(o["district"] or o["name"])))

    cache_file.write_text(json.dumps(
        {"v": 2, "service": service_name, "fetched": datetime.now().isoformat(),
         "offices": offices}, ensure_ascii=False, indent=1))
    return service_name, offices


def check_location(browser, url):
    """Walk the booking flow for one location.

    Returns (dates, status): a sorted list of bookable dates like
    '11.09.2026', and a status string ('ok', 'throttled', 'blocked').
    """
    ctx = browser.new_context(locale="de-DE")
    try:
        page = ctx.new_page()
        # Avoid downloading assets that calendar parsing does not need.
        page.route(
            re.compile(r"\.(png|jpe?g|gif|svg|woff2?|ico|css)(\?|$)"),
            lambda route: route.abort(),
        )
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # The access-check page reloads after its JavaScript finishes.
        for _ in range(6):
            if "Unerwünschter Zugriff" not in (page.title() or ""):
                break
            page.wait_for_timeout(5000)
        else:
            return [], "blocked"

        # An empty preference form requests all days and times.
        if page.query_selector("form.timeselector"):
            page.click("form.timeselector button[type=submit]")
            page.wait_for_load_state("domcontentloaded")

        page.wait_for_timeout(1500)
        html = page.content()

        if "Zu viele Zugriffe" in html or "429" in (page.title() or ""):
            return [], "throttled"

        dates = set(BOOKABLE_RE.findall(html))

        # Each calendar page covers two months; include the next page too.
        m = NEXT_MONTH_RE.search(html)
        if m:
            next_path = m.group(1) or m.group(2)
            page.goto(
                "https://service.berlin.de" + next_path,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(1000)
            dates |= set(BOOKABLE_RE.findall(page.content()))

        return sorted(dates, key=lambda d: d.split(".")[::-1]), "ok"
    finally:
        try:
            ctx.close()
        except Exception:
            pass  # driver may already be gone (e.g. after Ctrl+C)
