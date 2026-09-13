"""Launching Silksong and reading its BepInEx log.

Starting the game is the one job that changes completely between platforms.
A Windows build loads BepInEx by itself, because winhttp.dll sits next to the
exe and Windows picks it up; the macOS and Linux builds have no such hook, so
the loader ships a run_bepinex.sh that sets DYLD_INSERT_LIBRARIES / LD_PRELOAD
and then execs the game. Running a native build any other way boots it vanilla,
which is the single most confusing way for modding to fail, so that script is
preferred over the executable whenever it is there.
"""

import os
import time

from . import config as cfg
from . import platforms as plat

BEPINEX_SCRIPT = "run_bepinex.sh"


class LaunchError(Exception):
    pass


def is_running():
    """True if a Silksong process (or its Wine wrapper) is already up."""
    return plat.game_is_running()


def resolve_wrapper(conf):
    """The .app to open. Falls back to walking up from the game folder."""
    wrapper = conf.wrapper
    if wrapper and wrapper.exists():
        return wrapper
    return cfg.wrapper_for(conf.game)


def from_steam(game_dir):
    """True if this copy sits inside a Steam library, Proton prefix included."""
    if game_dir is None:
        return False
    parts = {part.lower() for part in game_dir.parts}
    return "steamapps" in parts or "steam" in parts


def loader_script(conf):
    """The run_bepinex.sh that belongs to this install, if it is usable."""
    if conf.game is None:
        return None
    script = conf.game / BEPINEX_SCRIPT
    return script if plat.is_file(script) else None


def launch(conf):
    """Start the game. Returns a short description of how it was started."""
    if not conf.configured:
        raise LaunchError("No game path configured. Run /setup first.")

    executable, build = plat.executable(conf.game)
    if executable is None:
        raise LaunchError("Couldn't find an executable in %s." % conf.game)

    if conf["launch_via_steam"]:
        described = _try_steam(conf, build)
        if described:
            return described

    wrapper = resolve_wrapper(conf)
    if conf["launch_via_wrapper"] and wrapper and plat.HOST == plat.MACOS:
        return _open_wrapper(wrapper)

    if build == plat.HOST:
        return _launch_native(conf, executable, build)
    if build == plat.WINDOWS:
        return _launch_windows_build(conf, executable, wrapper)
    raise LaunchError(
        "This is the %s build and you're on %s. Beastfly can manage its mods,\n"
        "  but only %s can run it." % (_build_name(build), plat.HOST_LABEL,
                                       _build_name(build)))


# ------------------------------------------------------------- strategies

def _launch_native(conf, executable, build):
    """A build compiled for this machine."""
    script = loader_script(conf)
    if script is not None and build != plat.WINDOWS:
        # The loader's own launcher: it exports the doorstop environment and
        # then execs the game, which is the only way mods load on macOS/Linux.
        plat.make_executable(script)
        try:
            plat.spawn(["/bin/sh", str(script), executable.name], cwd=conf.game)
        except OSError as error:
            raise LaunchError("Could not run %s (%s)." % (BEPINEX_SCRIPT, error))
        return "%s (mods loaded)" % BEPINEX_SCRIPT

    if build == plat.MACOS:
        opener = plat.opener()
        if opener is None:
            raise LaunchError("Couldn't find `open` to start %s." % executable.name)
        try:
            plat.spawn(opener + [str(executable)])
        except OSError as error:
            raise LaunchError("Could not open %s (%s)." % (executable.name, error))
        return executable.name

    try:
        plat.spawn([str(executable)], cwd=conf.game)
    except OSError as error:
        raise LaunchError("Could not start the game (%s)." % error)
    return "the %s build" % _build_name(build).lower()


def _launch_windows_build(conf, executable, wrapper):
    """A Windows build on a Mac or a Linux box: something has to translate."""
    if wrapper:
        if plat.HOST == plat.MACOS:
            return _open_wrapper(wrapper)
        raise LaunchError(
            "%s is a macOS wrapper and this is %s. Point the Silksong path at\n"
            "  the Wine prefix instead, via /settings."
            % (wrapper.name, plat.HOST_LABEL))

    prefix = plat.prefix_of(conf.game)
    wine = plat.wine_command()
    if prefix is not None and wine:
        environment = dict(os.environ, WINEPREFIX=str(prefix.parent))
        try:
            plat.spawn([wine, str(executable)], cwd=conf.game, env=environment)
        except OSError as error:
            raise LaunchError("Could not start Wine (%s)." % error)
        return "wine in %s" % prefix.parent.name

    described = _try_steam(conf, plat.WINDOWS)
    if described:
        return described

    if conf["launch_via_wrapper"]:
        raise LaunchError(
            "This is the Windows build and nothing here can run it directly.\n"
            "  Install Wine, or start it from Steam/Lutris/Porting Kit yourself -\n"
            "  mods are already in place either way.")
    raise LaunchError(
        "'Launch through Wine wrapper' is off and this is the Windows build.\n"
        "  Turn it back on in /settings, or start the game yourself.")


def _try_steam(conf, build):
    """Hand the game to Steam, if Steam is here and this copy came from it."""
    if not from_steam(conf.game):
        return None
    command = plat.steam_command()
    if command is None:
        return None
    try:
        plat.spawn(command)
    except OSError:
        return None
    if build != plat.WINDOWS and loader_script(conf) is not None:
        # Steam starts the executable, not run_bepinex.sh, so unless the user
        # has set launch options the game comes up vanilla.
        return "Steam (set launch options for mods - see /path)"
    return "Steam"


def _open_wrapper(wrapper):
    """Exactly what double-clicking the wrapper in Finder does."""
    opener = plat.opener()
    if opener is None:
        raise LaunchError(
            "Opening a .app wrapper needs macOS. On Linux, point the Silksong "
            "path at your Wine prefix and launch it yourself.")
    try:
        plat.spawn(opener + [str(wrapper)])
    except OSError as error:
        raise LaunchError("Could not open %s (%s)." % (wrapper.name, error))
    return wrapper.name


def _build_name(build):
    return {plat.WINDOWS: "Windows", plat.MACOS: "macOS",
            plat.LINUX: "Linux"}.get(build, str(build))


def steam_launch_options(conf):
    """The Steam launch-options line that makes a native build load mods.

    Steam runs the game's own executable, so on macOS and Linux the loader has
    to be wedged in front of it. There is no API for this - the string has to
    be pasted into Steam by hand.
    """
    script = loader_script(conf)
    if script is None or plat.HOST == plat.WINDOWS:
        return None
    return '"%s" %%command%%' % script


# ------------------------------------------------------------------ logs

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
