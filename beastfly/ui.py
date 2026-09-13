"""Terminal presentation: colour, symbols, the beastfly mark, small layout helpers."""

import os
import re
import shutil
import sys

VERSION = "0.1.1"


def _prepare_windows_console():
    """Make the Windows console speak UTF-8 before anything is printed.

    The menus and headers are built from ✓, · and box-drawing characters. A
    console left on a legacy code page, or a redirected stdout that inherited
    cp1252, raises UnicodeEncodeError on the first one of those.
    """
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _enable_windows_colour():
    """Turn on ANSI handling in the Windows console.

    Windows Terminal and PowerShell understand escape codes, but only once a
    process asks for them. Without this, colour would have to be switched off
    on Windows entirely - TERM is never set there, so the check below would
    already have decided that.
    """
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # -11 is STD_OUTPUT_HANDLE, 0x4 is ENABLE_VIRTUAL_TERMINAL_PROCESSING.
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x4))
    except Exception:
        return False


_WINDOWS = os.name == "nt"
if _WINDOWS:
    _prepare_windows_console()

_COLOR = (
    sys.stdout.isatty()
    and os.environ.get("NO_COLOR") is None
    and (_enable_windows_colour() if _WINDOWS
         else os.environ.get("TERM") not in (None, "", "dumb"))
)

# ✓ and ✗ carry meaning - enabled or not - so on a console that can't encode
# them they fall back to ASCII rather than printing as a replacement character.
# Decoration elsewhere (rules, arrows) is allowed to degrade.
try:
    "✓ ● ═".encode(sys.stdout.encoding or "utf-8")
    _UNICODE = True
except (UnicodeEncodeError, LookupError):
    _UNICODE = False


def _sgr(code):
    def wrap(text):
        if not _COLOR:
            return str(text)
        return "\033[%sm%s\033[0m" % (code, text)
    return wrap


bold = _sgr("1")
dim = _sgr("2")
accent = _sgr("38;5;168")   # Hornet crimson
ok = _sgr("38;5;114")       # enabled / present
bad = _sgr("38;5;167")      # disabled / missing
warn = _sgr("38;5;179")     # update available
grey = _sgr("38;5;245")
white = _sgr("38;5;253")

ON = "✓" if _UNICODE else "+"
OFF = "✗" if _UNICODE else "-"
ACTIVE = "●" if _UNICODE else "*"
UPDATE = "↑" if _UNICODE else "^"


def title():
    """One-line header. No ASCII art - it never read well at terminal size."""
    return (bold(accent("beastfly")) + grey(" " + VERSION)
            + grey("  ·  Silksong mod manager"))


_ANSI = re.compile(r"\033\[[0-9;]*m")


def visible_len(text):
    """Length as the terminal sees it, ignoring colour escapes."""
    return len(_ANSI.sub("", str(text)))


def pad(text, columns):
    """ljust that stays correct once colour has been applied."""
    return str(text) + " " * max(0, columns - visible_len(text))


def truncate_visible(text, limit):
    """Truncate to `limit` visible columns, keeping colour escapes intact."""
    text = str(text)
    if visible_len(text) <= limit:
        return text
    out, shown, index = [], 0, 0
    while index < len(text) and shown < limit:
        if text[index] == "\033":
            end = text.find("m", index)
            if end == -1:
                break
            out.append(text[index:end + 1])
            index = end + 1
            continue
        out.append(text[index])
        shown += 1
        index += 1
    return "".join(out) + "\033[0m"


def width(default=80):
    return max(40, min(shutil.get_terminal_size((default, 24)).columns, 100))


def header(text, rule="═"):
    """A title with a full-width rule under it."""
    return bold(white(text)) + "\n" + grey(rule * min(width(), 46))


def section(text):
    return grey(text.upper())


def field(label, value, pad=30):
    return "  " + white(str(label).ljust(pad)) + grey(str(value))


def state(enabled):
    return ok(ON) if enabled else bad(OFF)


def plural(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


def truncate(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def info(msg):
    print(grey("  " + msg))


def good(msg):
    print("  " + ok(ON) + " " + msg)


def fail(msg):
    print("  " + bad(OFF) + " " + msg)


def note(msg):
    print("  " + warn("!") + " " + msg)


def confirm(question, default=False):
    """Ask a yes/no question. Returns default on EOF so scripted runs don't hang."""
    hint = "Y/n" if default else "y/N"
    try:
        answer = input("  " + question + " " + grey("[" + hint + "]") + " ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def ask(question, current=""):
    suffix = grey(" [" + truncate(current, 40) + "]") if current else ""
    try:
        answer = input("  " + question + suffix + "\n  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return answer or None


def choose(prompt, options, render=str):
    """Numbered picker. Returns the chosen item, or None if cancelled."""
    if not options:
        return None
    if len(options) == 1:
        return options[0]
    print()
    for i, option in enumerate(options, 1):
        print("  " + accent("[%d]" % i) + " " + render(option))
    print()
    raw = ask(prompt + " (number, or blank to cancel)")
    if not raw or not raw.isdigit():
        return None
    index = int(raw)
    if 1 <= index <= len(options):
        return options[index - 1]
    return None


def progress(label, done, total):
    """Single-line download meter, redrawn in place."""
    if not _COLOR or not total:
        return
    span = 24
    filled = int(span * done / total) if total else 0
    bar = "█" * filled + grey("░" * (span - filled))
    pct = 100 * done / total if total else 0
    sys.stdout.write("\r  %s %s %3.0f%%" % (truncate(label, 22).ljust(22), bar, pct))
    sys.stdout.flush()


def progress_done():
    if _COLOR:
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
