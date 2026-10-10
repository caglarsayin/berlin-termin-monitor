# Development

`./start` prepares the local environment and runs `termin_monitor.py`, forwarding
all arguments. You can also run `python3 termin_monitor.py` from an environment
with Playwright installed. Application code lives in
the `termin/` package:

| Module | Responsibility |
| --- | --- |
| `cli.py` | Argument parsing and mode dispatch |
| `app.py` | Application flows, worker lifecycle, and signal handling |
| `providers/berlin.py`, `providers/doctolib.py` | Discovery, browser navigation, and response parsing |
| `workers/berlin.py`, `workers/doctolib.py` | Polling, retries, scheduling, and alert dispatch |
| `ledger.py` | Slot history, day transitions, and availability summaries |
| `model.py` | State shared by the dashboard and workers |
| `storage.py`, `paths.py` | JSON persistence and runtime file locations |
| `terminal.py` | Keyboard input, colors, and reusable menus |
| `ui/setup.py`, `ui/dashboard.py` | Configuration screens and rendering |
| `alerts.py`, `diagnostics.py` | macOS notifications, sounds, and diagnostic logging |

Provider modules do not start polling loops. Workers receive a model and an
update callback; `app.py` connects them to the interactive or headless UI.
Keep availability-transition rules in `ledger.py` and file-format handling in
`storage.py`, so those behaviors can be checked independently of the browser.

Runtime files retain their existing locations beside the launcher, regardless
of the working directory. Existing configuration and ledger files require no
migration. The internal Python modules are implementation details; the
supported entry point is the launcher.

Run the offline regression suite with Python's standard library:

```sh
python3 -B -m unittest discover -s tests -v
```

Tests use temporary files and simulated browser responses. They do not require
Chrome or Playwright, contact appointment services, or send notifications.

### What belongs in Git

Commit the launcher, `termin/` source, `tests/`, documentation, and shared
project configuration such as `.gitignore`. Keep future dependency manifests
and license files in Git too.

Personal configuration, the browser profile, availability history, office
caches, logs, and debug captures are excluded by `.gitignore`. These are local
runtime data and may contain personal information or session cookies. Use
invented data for examples and test fixtures; do not force-add ignored files.

Before committing, review `git status --short` and `git diff --cached` to check
the actual files and content being included.
