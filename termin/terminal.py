"""Terminal colors, keyboard input, and reusable selection menus."""

import os
import select
import sys
import termios
import tty


IS_TTY = sys.stdout.isatty()


BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"


GREEN, YELLOW, RED, CYAN = "\033[32m", "\033[33m", "\033[31m", "\033[36m"


BLUE, GRAY, STRIKE = "\033[94m", "\033[90m", "\033[9m"


def c(code, text):
    return f"{code}{text}{RESET}" if IS_TTY else text


def clear_screen():
    if IS_TTY:
        sys.stdout.write("\033[H\033[2J\033[3J")
        sys.stdout.flush()


def ask(prompt):
    """input() that exits gracefully on Ctrl+C / Ctrl+D."""
    try:
        return input(prompt)
    except (KeyboardInterrupt, EOFError):
        print("\n\n  bye 👋")
        sys.exit(0)


MENU_KEYS = sys.stdin.isatty() and IS_TTY and os.environ.get("TERM", "") != "dumb"


_ESC_KEYS = {"[A": "up", "OA": "up", "[B": "down", "OB": "down",
             "[C": "right", "OC": "right", "[D": "left", "OD": "left"}


def _read_key():
    """Read one keypress, decoding arrow-key escape sequences.

    Returns None for escape sequences we don't care about — callers ignore it.
    """
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        # TCSANOW preserves buffered keys already detected by select().
        tty.setcbreak(fd, termios.TCSANOW)
        ch = os.read(fd, 1).decode("utf-8", "ignore")
        if ch == "\x1b":
            seq = ""
            while len(seq) < 8 and select.select([fd], [], [], 0.03)[0]:
                seq += os.read(fd, 1).decode("utf-8", "ignore")
                if seq in _ESC_KEYS:
                    return _ESC_KEYS[seq]
            if not seq:
                return "esc"
            return None
        if ch in ("\r", "\n"):
            return "enter"
        if ch in ("", "\x04"):  # EOF / Ctrl+D
            return "esc"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _run_menu(header_lines, entries, multi=False, default_idx=0, checked=None):
    """Interactive menu. entries: [{label, value, note?, disabled?}].

    Single-select: Enter/digit returns the focused entry's value, Esc/q None.
    Multi-select:  Space/digit toggles, 'a' all/none, Enter returns the list
    of checked values (at least one), Esc/q None.
    """
    enabled = [i for i, e in enumerate(entries) if not e.get("disabled")]
    if not enabled:
        return None
    try:
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)  # drop stale type-ahead
    except termios.error:
        pass
    idx = default_idx if default_idx in enabled else enabled[0]
    checked = set(checked or [])
    hint = ("↑↓ move · Space toggle · a all/none · Enter confirm · Esc back"
            if multi else "↑↓ move · Enter select · Esc back")
    drawn, warn = 0, ""
    sys.stdout.write("\033[?25l")
    try:
        while True:
            lines = list(header_lines)
            for i, e in enumerate(entries):
                note = e.get("note", "")
                if e.get("disabled"):
                    lines.append("      " + c(DIM, f"✕ {e['label']}{note}"))
                    continue
                pointer = c(GREEN, "❯ ") if i == idx else "  "
                box = (c(GREEN, "◉ ") if i in checked else c(DIM, "○ ")) if multi else ""
                label = c(BOLD + CYAN, e["label"]) if i == idx else e["label"]
                lines.append(f"    {pointer}{box}{label}{note}")
            lines.append("")
            lines.append("  " + (c(YELLOW, warn) if warn else c(DIM, hint)))
            if drawn:
                sys.stdout.write(f"\033[{drawn}A\033[J")
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
            drawn, warn = len(lines), ""

            k = _read_key()
            if not k:
                continue
            if k in ("up", "k"):
                idx = enabled[(enabled.index(idx) - 1) % len(enabled)]
            elif k in ("down", "j"):
                idx = enabled[(enabled.index(idx) + 1) % len(enabled)]
            elif k == "enter":
                if not multi:
                    return entries[idx]["value"]
                if checked:
                    return [entries[i]["value"] for i in sorted(checked)]
                warn = "select at least one — Space toggles"
            elif k == " " and multi:
                checked ^= {idx}
            elif k == "a" and multi:
                checked = set() if checked == set(enabled) else set(enabled)
            elif k.isdigit() and (int(k) - 1) in enabled:
                if multi:
                    checked ^= {int(k) - 1}
                else:
                    return entries[int(k) - 1]["value"]
            elif k in ("esc", "q"):
                return None
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def menu_header(subtitle=""):
    lines = ["", c(BOLD + CYAN, "  ══ Berlin Termin Monitor ══"), ""]
    if subtitle:
        lines += ["  " + subtitle, ""]
    return lines


def ask_url(prompt):
    """Read a pasted URL with our own echo.

    Terminal echo can be unreliable right after raw-mode menus (Cmd+V pastes
    showed up invisible for some setups), and pastes copied from wrapped text
    contain line breaks that would leak into the next prompt. So: read raw,
    print each character ourselves, glue multi-line pastes, strip
    bracketed-paste escape markers, and support backspace."""
    if not sys.stdin.isatty():
        return "".join(ask(prompt).split())
    sys.stdout.write(prompt)
    sys.stdout.flush()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    buf = ""
    try:
        tty.setcbreak(fd, termios.TCSANOW)
        pending_submit = False
        while True:
            ready = select.select([fd], [], [], 0.15 if pending_submit else None)[0]
            if not ready:
                break  # newline seen and nothing followed: that was Enter
            chunk = os.read(fd, 4096).decode("utf-8", "ignore")
            if not chunk:
                break
            pending_submit = False
            i = 0
            while i < len(chunk):
                ch = chunk[i]
                if ch == "\x1b":  # skip escape sequences (paste markers etc.)
                    j = i + 1
                    while j < len(chunk) and chunk[j] not in "~ABCDHFR":
                        j += 1
                    i = j + 1
                    continue
                if ch in ("\r", "\n"):
                    if i < len(chunk) - 1:
                        i += 1  # newline inside a paste: glue the lines
                        continue
                    pending_submit = True
                    i += 1
                    continue
                if ch in ("\x7f", "\x08"):
                    if buf:
                        buf = buf[:-1]
                        sys.stdout.write("\b \b")
                elif ch == "\x03":
                    raise KeyboardInterrupt
                elif ch == "\x04":
                    pending_submit = True
                elif ch.isprintable():
                    buf += ch
                    sys.stdout.write(ch)
                i += 1
            sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()
        return "".join(buf.split())
    except KeyboardInterrupt:
        print("\n\n  bye 👋")
        sys.exit(0)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
