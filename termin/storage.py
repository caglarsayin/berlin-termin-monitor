"""Configuration and availability-ledger persistence using the existing JSON formats."""

import json

from termin.paths import CONFIG_FILE, DOCTOLIB_LEDGER_FILE


def _upgrade_office(o, service_id):
    """Fill fields that files written by older versions are missing."""
    o.setdefault("service_id", service_id)
    o.setdefault("paused", False)
    if not o.get("book") and o.get("tag"):
        o["book"] = (f"https://service.berlin.de/terminvereinbarung/termin/tag.php"
                     f"?id={o['tag']}&anliegen[]={service_id}")


def load_ledger():
    try:
        return json.loads(DOCTOLIB_LEDGER_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_ledger(ledger):
    try:
        DOCTOLIB_LEDGER_FILE.write_text(json.dumps(ledger))
    except OSError:
        pass


def load_config():
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text())
            if config.get("offices") and config.get("service_id"):
                for o in config["offices"]:
                    _upgrade_office(o, config["service_id"])
            return config
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _save_cfg_patch(**fields):
    """Update only the given keys so the berlin/doctolib/mode sections never
    overwrite each other."""
    cfg = load_config() or {}
    cfg.update(fields)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1))


def save_config(service_id, service_name, offices):
    _save_cfg_patch(service_id=service_id, service_name=service_name,
                    offices=offices)


def save_doctolib(watches):
    _save_cfg_patch(doctolib=watches)


def save_mode(mode):
    _save_cfg_patch(mode=mode)


def save_selection(model):
    """Persist the current watch list, whichever mode we're in."""
    if model.mode == "doctolib":
        save_doctolib(model.offices)
    else:
        save_config(model.service_id, model.service_name, model.offices)
