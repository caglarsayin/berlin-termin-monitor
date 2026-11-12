"""Doctolib booking URLs, browser navigation, and availability-feed parsing."""

import json
import os
import socket
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from termin.diagnostics import log_debug
from termin.paths import DEBUG_DIR, DL_PROFILE_DIR, UA


def clean_wizard_url(url):
    """Normalize a pasted booking-wizard URL; drop the patient identity."""
    url = "".join(ch for ch in url if ch.isprintable())
    p = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if k != "masterPatientUuid"]
    return urlunsplit((p.scheme or "https", p.netloc or "www.doctolib.de",
                       p.path, urlencode(q), ""))


def suggest_label(url):
    segs = [s for s in urlsplit(url).path.split("/") if s]
    if "booking" in segs:
        segs = segs[:segs.index("booking")]
    return " · ".join(s.replace("-", " ") for s in reversed(segs[-3:])) or "doctolib watch"


def parse_doctolib_feed(body):
    """Return (sorted slot keys 'YYYY-MM-DDTHH:MM', next_slot date or None)."""
    d = json.loads(body)
    slots = set()
    for day in d.get("availabilities", []):
        for s in day.get("slots", []):
            iso = s if isinstance(s, str) else (s.get("start_date") or s.get("startDate") or "")
            if len(iso) >= 16:
                slots.add(iso[:16])
    nxt = d.get("next_slot")
    return sorted(slots), (nxt[:10] if isinstance(nxt, str) else None)


def _classify_block(page, doc_status, wizard_url):
    """Name the failure mode so logs and the UI say WHY, not just 'failed'."""
    title = ""
    try:
        title = page.title() or ""
    except Exception:
        pass
    if doc_status == 403 or not title.strip():
        return "challenge-403"
    if "moment" in title.lower():  # 'Nur einen Moment…' interstitial
        return "challenge-interstitial"
    if "/booking" in wizard_url and "/booking" not in (page.url or ""):
        return "redirect-off-funnel"
    return "funnel-no-feed"


def _capture_evidence(page, tag):
    """Save what Doctolib actually served (screenshot + HTML), ring-buffered."""
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        base = DEBUG_DIR / f"{datetime.now():%d%m-%H%M%S}-{tag}"
        page.screenshot(path=f"{base}.png")
        Path(f"{base}.html").write_text(
            f"<!-- url: {page.url} -->\n" + page.content()[:400000])
        files = sorted(DEBUG_DIR.iterdir(), key=lambda f: f.stat().st_mtime)
        for f in files[:-20]:
            f.unlink()
        log_debug(f"evidence saved: {base.name}.png/.html")
    except Exception as e:
        log_debug(f"evidence capture failed: {e!r}")


def dl_load(page, wizard_url):
    """Open the wizard and let the page itself fetch availability.

    Doctolib's anti-bot layer accepts the app's own requests but rejects
    script-injected fetches of the same URL, so polling means loading the
    page and reading the availabilities.json responses it triggers.
    Returns (feed_url, [response bodies], fail_reason)."""
    responses = []
    doc_status = None

    def on_response(resp):
        if "availabilities.json" in resp.url:
            responses.append(resp)

    page.on("response", on_response)
    try:
        skip = ("zurück", "back", "einloggen", "login", "weitere daten", "hilfe")
        for round_no in (1, 2):
            if round_no == 2 and "/booking" in wizard_url:
                # Retry redirects by visiting the profile before the booking page.
                try:
                    page.goto(wizard_url.split("/booking")[0],
                              wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass
            nav = page.goto(wizard_url, wait_until="domcontentloaded", timeout=60000)
            doc_status = nav.status if nav else None
            page.wait_for_timeout(4000)
            if "/booking" in wizard_url and "/booking" not in (page.url or ""):
                log_debug(f"redirected off the booking funnel to {page.url[:90]} "
                          f"— soft anti-bot deflection")
            try:
                btn = page.query_selector("#didomi-notice-agree-button")
                if btn:
                    btn.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass
            for _ in range(4):
                if responses:
                    break
                clicked = False
                for sel in ("main [role=radio]", "main input[type=radio]",
                            "main li button", "main button"):
                    try:
                        for el in page.query_selector_all(sel):
                            text = (el.inner_text() or "").strip().lower()
                            if any(s in text for s in skip):
                                continue
                            el.click()
                            clicked = True
                            break
                    except Exception:
                        continue
                    if clicked:
                        break
                page.wait_for_timeout(4000)
            if any(r.status == 200 for r in responses):
                break
            if round_no == 1:
                log_debug("no usable availability response — retrying after a pause")
                page.wait_for_timeout(9000)
                responses.clear()
        if responses:
            page.wait_for_timeout(3000)  # Allow additional availability responses to arrive.

        bodies = []
        for r in list(responses):
            try:
                if r.status == 200:
                    bodies.append(r.text())
                else:
                    log_debug(f"availabilities response {r.status}: {r.url[:110]}")
            except Exception as e:
                log_debug(f"could not read response body: {e!r}")
        reason = None
        if not bodies:
            reason = _classify_block(page, doc_status, wizard_url)
            log_debug(f"check failed [{reason}] doc_status={doc_status} "
                      f"url={page.url[:90]}")
            _capture_evidence(page, reason)
        return (responses[0].url if responses else None), bodies, reason
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass


def dl_check(page, watch):
    """Poll one watch via a page load. Returns (slots, next_slot, feed,
    fail_reason) — slots None when nothing readable came back."""
    feed, bodies, reason = dl_load(page, watch["book"])
    if not bodies:
        return None, None, feed or watch.get("feed"), reason or "no-data"
    slots, nxt = set(), None
    for body in bodies:
        try:
            got, n = parse_doctolib_feed(body)
            slots.update(got)
            nxt = n or nxt
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            log_debug(f"{watch['name']}: parse error {e!r}: {body[:110]}")
    log_debug(f"{watch['name']}: {len(slots)} slot(s) in {len(bodies)} window(s), "
              f"next_slot={nxt}")
    return sorted(slots), nxt, feed, None


def clear_stale_profile_lock(profile=DL_PROFILE_DIR):
    """Remove Chrome's singleton lock left by another host (e.g. a recreated container).

    Chrome refuses a profile whose SingletonLock ('<hostname>-<pid>') names a
    different host. Locks from this host are left for Chrome to validate itself.
    Returns True when a stale lock was removed."""
    lock = Path(profile) / "SingletonLock"
    try:
        target = os.readlink(lock)
    except OSError:
        return False
    if target.rsplit("-", 1)[0] == socket.gethostname():
        return False
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (Path(profile) / name).unlink()
        except FileNotFoundError:
            pass
    log_debug(f"removed stale browser profile lock from host {target.rsplit('-', 1)[0]}")
    return True


def dl_probe(wizard_url):
    """One-shot discovery used by the add-a-doctor flow."""
    from playwright.sync_api import sync_playwright
    clear_stale_profile_lock()
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            str(DL_PROFILE_DIR), channel="chrome", headless=True,
            locale="de-DE", user_agent=UA)
        try:
            page = browser.pages[0] if browser.pages else browser.new_page()
            feed, bodies, _reason = dl_load(page, wizard_url)
            slots, nxt = set(), None
            for body in bodies:
                try:
                    got, n = parse_doctolib_feed(body)
                    slots.update(got)
                    nxt = n or nxt
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
            return feed, sorted(slots), nxt
        finally:
            try:
                browser.close()
            except Exception:
                pass
