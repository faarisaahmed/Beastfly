"""Arrow-key pickers.

A checklist for turning mods on and off, and a single-choice list for switching
profiles. Both redraw in place and scroll when the list is taller than the
terminal. Neither is available without an interactive terminal, so callers must
check `available()` and keep a typed fallback.
"""

import os
import select
import sys

from . import ui

try:
    import termios
    import tty
    RAW_AVAILABLE = True
except ImportError:                                  # pragma: no cover
    RAW_AVAILABLE = False

CTRL_C, ENTER, ESC, SPACE = 3, 13, 27, 32


def available():
    return RAW_AVAILABLE and sys.stdin.isatty() and sys.stdout.isatty()


class Row:
    def __init__(self, label, meta="", checked=False, payload=None):
        self.label = label
        self.meta = meta
        self.checked = checked
        self.payload = payload


class _Picker:
    def __init__(self, header, rows, multi, footer="", actions=None):
        self.header = header
        self.rows = rows
        self.multi = multi
        self.footer = footer
        # Extra single-key actions, e.g. {"d": "delete"}. Returned to the caller
        # so it can prompt in cooked mode and then reopen the list.
        self.actions = actions or {}
        self.cursor = 0
        self.offset = 0
        self.drawn = 0

    # ---------------------------------------------------------- layout

    def viewport(self):
        try:
            lines = os.get_terminal_size().lines
        except OSError:
            lines = 24
        # header + blank + footer + prompt breathing room
        return max(3, min(len(self.rows), lines - 6))

    def scroll(self):
        span = self.viewport()
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + span:
            self.offset = self.cursor - span + 1
        self.offset = max(0, min(self.offset, max(0, len(self.rows) - span)))

    def lines(self):
        self.scroll()
        span = self.viewport()
        width = ui.width()
        out = [self.header, ""]

        if self.offset:
            out.append(ui.grey("     ↑ %d more" % self.offset))
        for index in range(self.offset, min(len(self.rows), self.offset + span)):
            row = self.rows[index]
            here = index == self.cursor
            marker = ui.accent("❯") if here else " "
            if self.multi:
                box = "[%s]" % (ui.ok(ui.ON) if row.checked else ui.bad(ui.OFF))
            else:
                box = "[%s]" % (ui.ok(ui.ON) if row.checked else " ")
            label = ui.truncate(row.label, 34)
            label = ui.bold(ui.white(label)) if here else ui.white(label)
            out.append(ui.truncate_visible(
                "  %s %s %s %s" % (marker, box, ui.pad(label, 36), ui.grey(row.meta)),
                width - 1))
        remaining = len(self.rows) - (self.offset + span)
        if remaining > 0:
            out.append(ui.grey("     ↓ %d more" % remaining))

        out.append("")
        out.append(ui.grey(self.footer))
        return out

    def render(self):
        out = sys.stdout
        if self.drawn:
            out.write("\033[%dA" % self.drawn)
        out.write("\r\033[J")
        lines = self.lines()
        for line in lines:
            out.write(line + "\r\n")
        out.flush()
        self.drawn = len(lines)

    def clear(self):
        """Wipe the picker so the caller can print its own result."""
        out = sys.stdout
        if self.drawn:
            out.write("\033[%dA" % self.drawn)
        out.write("\r\033[J")
        out.flush()
        self.drawn = 0

    # ---------------------------------------------------------- loop

    def run(self):
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            self.render()
            while True:
                code = os.read(fd, 1)
                if not code:
                    return None
                byte = code[0]

                if byte in (CTRL_C, ord("q"), ord("Q")):
                    return None
                if byte in (ENTER, 10):
                    return ("select", self.cursor)
                character = chr(byte) if 32 <= byte < 127 else ""
                if character in self.actions:
                    return ("action", character, self.cursor)
                if byte == SPACE and self.multi:
                    self.rows[self.cursor].checked = not self.rows[self.cursor].checked
                elif byte == ord("j"):
                    self.cursor = (self.cursor + 1) % len(self.rows)
                elif byte == ord("k"):
                    self.cursor = (self.cursor - 1) % len(self.rows)
                elif byte == ord("a") and self.multi:
                    for row in self.rows:
                        row.checked = True
                elif byte == ord("n") and self.multi:
                    for row in self.rows:
                        row.checked = False
                elif byte == ord("i") and self.multi:
                    for row in self.rows:
                        row.checked = not row.checked
                elif byte == ESC:
                    action = _escape(fd)
                    if action == "up":
                        self.cursor = (self.cursor - 1) % len(self.rows)
                    elif action == "down":
                        self.cursor = (self.cursor + 1) % len(self.rows)
                    elif action == "home":
                        self.cursor = 0
                    elif action == "end":
                        self.cursor = len(self.rows) - 1
                    elif action == "pageup":
                        self.cursor = max(0, self.cursor - self.viewport())
                    elif action == "pagedown":
                        self.cursor = min(len(self.rows) - 1,
                                          self.cursor + self.viewport())
                    elif action is None:
                        return None            # bare Esc cancels
                elif not self.multi and byte == SPACE:
                    return ("select", self.cursor)
                self.render()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _escape(fd):
    sequence = ""
    while len(sequence) < 6:
        ready, _, _ = select.select([fd], [], [], 0.02)
        if not ready:
            break
        sequence += os.read(fd, 1).decode("latin-1")
        if sequence[-1].isalpha() or sequence[-1] == "~":
            break
    return {
        "[A": "up", "OA": "up", "[B": "down", "OB": "down",
        "[H": "home", "OH": "home", "[1~": "home",
        "[F": "end", "OF": "end", "[4~": "end",
        "[5~": "pageup", "[6~": "pagedown",
    }.get(sequence)


def checklist(header, rows, footer=None):
    """Toggle many. Returns the rows with .checked updated, or None if cancelled."""
    if not rows:
        return None
    footer = footer or ("↑↓ move   space toggle   a all   n none   i invert   "
                        "enter save   q cancel")
    view = _Picker(header, rows, multi=True, footer=footer)
    result = view.run()
    view.clear()
    return rows if result and result[0] == "select" else None


def choose(header, rows, footer=None):
    """Pick one. Returns the chosen Row, or None if cancelled."""
    if not rows:
        return None
    footer = footer or "↑↓ move   enter select   q cancel"
    view = _Picker(header, rows, multi=False, footer=footer)
    _start_on_checked(view, rows)
    result = view.run()
    view.clear()
    if result is None or result[0] != "select":
        return None
    return rows[result[1]]


def _start_on_checked(view, rows):
    for index, row in enumerate(rows):
        if row.checked:
            view.cursor = index
            break


def manage(header, rows, actions, footer=None):
    """Single-select list with extra action keys.

    Returns ("select", Row), ("action", key, Row), or None if cancelled. The
    caller handles the action - typically by prompting for text and reopening.
    """
    if not rows:
        return None
    footer = footer or "↑↓ move   enter select   q cancel"
    view = _Picker(header, rows, multi=False, footer=footer, actions=actions)
    _start_on_checked(view, rows)
    result = view.run()
    view.clear()
    if result is None:
        return None
    if result[0] == "select":
        return ("select", rows[result[1]])
    return ("action", result[1], rows[result[2]])
