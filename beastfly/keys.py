"""Reading single keystrokes, on a terminal that has no line editor in the way.

The arrow-key menus are the whole point of Beastfly's interface, and they need
raw keystrokes. POSIX gets those by putting the terminal in raw mode and
reading the tty; Windows has no termios at all and instead hands them over one
at a time through msvcrt, with arrow keys arriving as a two-byte code rather
than an escape sequence.

Rather than teach the pickers two dialects, Windows special keys are translated
into the same ANSI escape sequences a Unix terminal would have sent, so
everything upstream sees one keyboard.
"""

import os
import sys
from contextlib import contextmanager

try:
    import select
    import termios
    import tty
    BACKEND = "termios"
except ImportError:                                  # pragma: no cover
    try:
        import msvcrt
        BACKEND = "msvcrt"
    except ImportError:                              # pragma: no cover
        BACKEND = None

RAW_AVAILABLE = BACKEND is not None


def available():
    """True when raw keystrokes can be read from a real terminal."""
    return RAW_AVAILABLE and sys.stdin.isatty() and sys.stdout.isatty()


@contextmanager
def raw(fd):
    """Put the terminal in raw mode for the duration, then put it back."""
    if BACKEND != "termios":
        # The Windows console never echoes what msvcrt reads, so there is no
        # mode to change - but the pending buffer must not outlive the picker.
        _pending.clear()
        yield
        return
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def read(fd):
    """The next byte as an int, blocking. None at end of input."""
    if _pending:
        return _pending.pop(0)
    if BACKEND == "termios":
        data = os.read(fd, 1)
        return data[0] if data else None
    if BACKEND == "msvcrt":
        return _read_windows()
    return None


def read_within(fd, timeout):
    """The next byte within `timeout` seconds, or None if nothing arrives.

    Used to tell a real escape sequence from a lone Esc keypress.
    """
    if _pending:
        return _pending.pop(0)
    if BACKEND == "termios":
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            return None
        data = os.read(fd, 1)
        return data[0] if data else None
    if BACKEND == "msvcrt":
        # Windows sends the whole special key at once, so anything still to
        # come is already in _pending - which was checked above.
        return _read_windows() if msvcrt.kbhit() else None
    return None


# ------------------------------------------------------------- Windows

# Bytes waiting to be handed out, once a Windows key has been expanded into
# the escape sequence its Unix equivalent would have produced.
_pending = []

# The second byte msvcrt returns after a \x00 or \xe0 lead-in.
_WINDOWS_KEYS = {
    "H": "[A", "P": "[B", "M": "[C", "K": "[D",
    "G": "[H", "O": "[F", "I": "[5~", "Q": "[6~", "S": "[3~",
}


def _read_windows():
    """One byte, expanding special keys into ANSI escape sequences."""
    while True:
        character = msvcrt.getwch()
        if character in ("\x00", "\xe0"):
            sequence = _WINDOWS_KEYS.get(msvcrt.getwch())
            if sequence is None:
                continue                     # F-keys and the like: ignore
            _pending.extend(ord(c) for c in sequence)
            return 0x1b                      # Esc, then the sequence above
        encoded = character.encode("utf-8", "replace")
        if not encoded:
            continue
        _pending.extend(encoded[1:])
        return encoded[0]
