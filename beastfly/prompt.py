"""An input line with a live slash-command menu.

Typing `/` opens a list of commands under the prompt; typing more filters it.
Up/Down move the highlight, Tab completes, Enter runs the highlighted command.

Falls back to plain input() whenever stdin isn't an interactive terminal, so
piping commands into beastfly still works.
"""

import codecs
import os
import re
import select
import sys

from . import ui

try:
    import termios
    import tty
    RAW_AVAILABLE = True
except ImportError:                                  # pragma: no cover
    RAW_AVAILABLE = False

MAX_ROWS = 8

# Control bytes we care about.
CTRL_C, CTRL_D, TAB, ENTER, ESC = 3, 4, 9, 13, 27
CTRL_A, CTRL_E, CTRL_K, CTRL_U, CTRL_W, CTRL_L = 1, 5, 11, 21, 23, 12
BACKSPACE = (8, 127)


class Entry:
    """One selectable menu row - a command, a subcommand, or an argument value."""

    def __init__(self, display, description="", insert=None, key="", more=False):
        self.display = display
        self.description = description
        # Buffer contents once this row is chosen.
        self.insert = display if insert is None else insert
        # What the typed text is compared against for command rows.
        self.key = (key or display).lower()
        # True when choosing this row should wait for more typing, not submit.
        self.more = more

    @classmethod
    def command(cls, name, hint, description):
        invocation = "/" + name + ((" " + hint) if hint else "")
        return cls(invocation, description,
                   insert="/" + name + (" " if hint else ""),
                   key=name, more=bool(hint))


def interactive():
    return RAW_AVAILABLE and sys.stdin.isatty() and sys.stdout.isatty()


class LineEditor:
    def __init__(self, prompt, entries, history, provider=None):
        self.prompt = prompt
        self.entries = entries
        self.history = history
        self.provider = provider
        self.buffer = ""
        self.cursor = 0
        self.selected = 0
        self.drawn = 0            # lines the last render occupied above input
        self.dismissed = False    # Esc hides the menu until the text changes
        self.history_index = len(history)
        self.stash = ""

    # ------------------------------------------------------------ menu

    def matches(self):
        """Rows to show, or [] when the menu has nothing to offer."""
        if self.dismissed or not self.buffer.startswith("/"):
            return []
        typed = self.buffer[1:].lower()

        # Command and subcommand names. `typed` may hold a space, which is what
        # lets "/profile " offer "profile create" and friends.
        found = [e for e in self.entries if e.key.startswith(typed)]
        if found and not (len(found) == 1 and found[0].key == typed.rstrip()):
            return found

        # Past the command name: ask the host what the argument could be.
        split = re.match(r"^/(\S+)\s(.*)$", self.buffer)
        if split and self.provider:
            return self.provider(split.group(1), split.group(2))
        return []

    def menu_rows(self, matches):
        rows = []
        columns = ui.width()
        visible = matches[: self.rows_available()]
        if self.selected >= max(1, len(visible)):
            self.selected = 0
        for index, entry in enumerate(visible):
            chosen = index == self.selected
            marker = ui.accent("❯") if chosen else " "
            shown = ui.truncate(entry.display, 30)
            label = ui.accent(shown) if chosen else ui.white(shown)
            text = ui.pad(label, 32) + ui.grey(entry.description)
            rows.append(ui.truncate_visible(" %s %s" % (marker, text), columns - 1))
        hidden = len(matches) - len(visible)
        if hidden > 0:
            rows.append(ui.grey("   +%d more" % hidden))
        return rows

    def rows_available(self):
        try:
            lines = os.get_terminal_size().lines
        except OSError:
            lines = 24
        return max(1, min(MAX_ROWS, lines - 3))

    # ------------------------------------------------------------ drawing

    def render(self):
        """Redraw in place: menu rows first, input line last, as Claude Code does.

        Raw mode disables ONLCR, so every line break here must be a literal
        CRLF - a bare "\\n" would line-feed without returning to column 0 and
        the whole block would stagger to the right.
        """
        out = sys.stdout
        columns = ui.width()
        matches = self.matches()
        # A wrapped input line breaks the cursor arithmetic below; drop the menu.
        wrapping = ui.visible_len(self.prompt) + len(self.buffer) >= columns - 1
        rows = [] if wrapping else self.menu_rows(matches)

        if self.drawn:
            out.write("\033[%dA" % self.drawn)      # back to the top of the block
        out.write("\r\033[J")                       # clear the old block
        for row in rows:
            out.write(row + "\r\n")
        out.write(self.prompt + self.buffer)
        out.write("\r\033[%dC" % (ui.visible_len(self.prompt) + self.cursor))
        out.flush()
        self.drawn = len(rows)

    def finish(self):
        """Drop the menu, leave the committed line on screen, move down one."""
        out = sys.stdout
        if self.drawn:
            out.write("\033[%dA" % self.drawn)
        out.write("\r\033[J" + self.prompt + self.buffer + "\r\n")
        out.flush()
        self.drawn = 0

    # ------------------------------------------------------------ editing

    def insert(self, text):
        self.buffer = self.buffer[: self.cursor] + text + self.buffer[self.cursor:]
        self.cursor += len(text)
        self.selected = 0
        self.dismissed = False

    def backspace(self):
        if self.cursor:
            self.buffer = self.buffer[: self.cursor - 1] + self.buffer[self.cursor:]
            self.cursor -= 1
            self.selected = 0
            self.dismissed = False

    def highlighted(self, matches):
        return matches[min(self.selected, len(matches) - 1)]

    def complete(self, matches):
        entry = self.highlighted(matches)
        self.buffer = entry.insert
        self.cursor = len(self.buffer)
        self.selected = 0

    def recall(self, delta):
        if not self.history:
            return
        if self.history_index == len(self.history):
            self.stash = self.buffer
        self.history_index = max(0, min(len(self.history), self.history_index + delta))
        self.buffer = (self.stash if self.history_index == len(self.history)
                       else self.history[self.history_index])
        self.cursor = len(self.buffer)
        self.selected = 0


def read_line(prompt, entries, history, provider=None):
    """Read one line with the slash menu. Raises EOFError / KeyboardInterrupt."""
    if not interactive():
        return input(prompt)

    editor = LineEditor(prompt, entries, history, provider)
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        tty.setraw(fd)
        editor.render()
        while True:
            byte = os.read(fd, 1)
            if not byte:
                raise EOFError
            code = byte[0]

            if code == CTRL_C:
                # With text on the line, the first Ctrl-C just clears it.
                # On an empty line it propagates, and the REPL counts it.
                if editor.buffer:
                    editor.buffer = ""
                    editor.cursor = 0
                    editor.selected = 0
                    editor.render()
                    continue
                raise KeyboardInterrupt
            if code == CTRL_D:
                if not editor.buffer:
                    raise EOFError
                continue
            if code in (ENTER, 10):
                matches = editor.matches()
                if matches and editor.buffer.startswith("/"):
                    entry = editor.highlighted(matches)
                    editor.complete(matches)
                    # Needs arguments: fill it in and wait rather than firing
                    # off a bare command that can only print its usage.
                    if entry.more:
                        editor.render()
                        continue
                editor.finish()
                return editor.buffer
            if code == TAB:
                matches = editor.matches()
                if matches:
                    editor.complete(matches)
                editor.render()
                continue
            if code in BACKSPACE:
                editor.backspace()
                editor.render()
                continue
            if code == CTRL_A:
                editor.cursor = 0
                editor.render()
                continue
            if code == CTRL_E:
                editor.cursor = len(editor.buffer)
                editor.render()
                continue
            if code == CTRL_U:
                editor.buffer = editor.buffer[editor.cursor:]
                editor.cursor = 0
                editor.render()
                continue
            if code == CTRL_K:
                editor.buffer = editor.buffer[: editor.cursor]
                editor.render()
                continue
            if code == CTRL_W:
                head = editor.buffer[: editor.cursor].rstrip()
                cut = head.rfind(" ") + 1
                editor.buffer = head[:cut] + editor.buffer[editor.cursor:]
                editor.cursor = cut
                editor.render()
                continue
            if code == CTRL_L:
                sys.stdout.write("\033[H\033[2J")
                editor.render()
                continue
            if code == ESC:
                _handle_escape(fd, editor)
                editor.render()
                continue
            if code < 32:
                continue

            # Printable text, possibly multi-byte UTF-8.
            text = decoder.decode(byte)
            if text:
                editor.insert(text)
                editor.render()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _handle_escape(fd, editor):
    """Arrow keys and friends. ESC alone closes the menu."""
    sequence = ""
    while len(sequence) < 6:
        ready, _, _ = select.select([fd], [], [], 0.02)
        if not ready:
            break
        sequence += os.read(fd, 1).decode("latin-1")
        if sequence[-1].isalpha() or sequence[-1] == "~":
            break

    matches = editor.matches()
    count = min(len(matches), editor.rows_available())
    if sequence in ("[A", "OA"):                      # up
        if count:
            editor.selected = (editor.selected - 1) % count
        else:
            editor.recall(-1)
    elif sequence in ("[B", "OB"):                    # down
        if count:
            editor.selected = (editor.selected + 1) % count
        else:
            editor.recall(1)
    elif sequence in ("[C", "OC"):                    # right
        editor.cursor = min(len(editor.buffer), editor.cursor + 1)
    elif sequence in ("[D", "OD"):                    # left
        editor.cursor = max(0, editor.cursor - 1)
    elif sequence in ("[H", "OH", "[1~"):
        editor.cursor = 0
    elif sequence in ("[F", "OF", "[4~"):
        editor.cursor = len(editor.buffer)
    elif sequence == "[3~":                           # delete
        if editor.cursor < len(editor.buffer):
            editor.buffer = (editor.buffer[: editor.cursor]
                             + editor.buffer[editor.cursor + 1:])
            editor.selected = 0
    elif not sequence:
        editor.dismissed = True
