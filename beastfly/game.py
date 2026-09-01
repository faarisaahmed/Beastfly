"""Launching Silksong and reading its BepInEx log."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


class LaunchError(Exception):
    pass


def is_running():
    """True if a Silksong process (or its Wine wrapper) is already up."""
    try:
        output = subprocess.run(["ps", "-Axo", "command"], capture_output=True,
                                text=True, timeout=10).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False
    for line in output.split("\n"):
        if "silksong" in line and "beastfly" not in line and "ps -axo" not in line:
            return True
    return False


def resolve_wrapper(conf):
    """The .app to open. Falls back to walking up from the game folder."""
    wrapper = conf.wrapper
    if wrapper and wrapper.exists():
        return wrapper
    game = conf.game
    if game is None:
        return None
    for parent in game.parents:
        if parent.name.endswith(".app"):
            return parent
    return None


def launch(conf):
    """Start the game. Returns a short description of how it was started."""
    if not conf.configured:
        raise LaunchError("No game path configured. Run /setup first.")

    wrapper = resolve_wrapper(conf)
    if conf["launch_via_porting_kit"] and wrapper:
        # Exactly what double-clicking the wrapper in Finder does. Doorstop is
        # configured inside the wrapper already, so enabled mods load.
        if sys.platform != "darwin" or not shutil.which("open"):
            raise LaunchError(
                "Opening a .app wrapper needs macOS. On Linux, point the "
                "Silksong path at your Wine prefix and launch it yourself.")
        try:
            subprocess.Popen(["open", str(wrapper)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            raise LaunchError("Could not open %s (%s)." % (wrapper.name, error))
        return wrapper.name

    exe = conf.game / "Hollow Knight Silksong.exe"
    native = conf.game / "Hollow Knight Silksong"
    if exe.exists() and not native.exists():
        if wrapper:
            raise LaunchError(
                "'Launch through Porting Kit' is off, but this is the Windows build.\n"
                "  Turn it back on in /settings, or open %s yourself." % wrapper.name)
        raise LaunchError(
            "This is the Windows build and no wrapper was found around it.\n"
            "  Set the Silksong path inside your Porting Kit .app via /settings.")

    if native.exists():
        try:
            subprocess.Popen([str(native)], cwd=str(conf.game),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            raise LaunchError("Could not start the game (%s)." % error)
        return "the native build"

    raise LaunchError("Couldn't find an executable in %s." % conf.game)


def log_path(conf):
    if not conf.bepinex:
        return None
    candidate = conf.bepinex / "LogOutput.log"
    return candidate if candidate.exists() else None


def read_log(conf, lines=40, only_errors=False):
    path = log_path(conf)
    if path is None:
        return None, []
    try:
        # BepInEx logs are UTF-8 but can carry stray bytes from mod output.
        content = path.read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return path, []
    if only_errors:
        content = [l for l in content
                   if any(tag in l for tag in ("Error", "Warning", "Exception", "Fatal"))]
    return path, [l for l in content if l.strip()][-lines:]


def log_age(conf):
    path = log_path(conf)
    if path is None:
        return None
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None
