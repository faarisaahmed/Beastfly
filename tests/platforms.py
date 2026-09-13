#!/usr/bin/env python3
"""Check install discovery, save lookup and launching for every platform.

Beastfly has to find a Steam install on Windows, a GOG install inside a Porting
Kit wrapper on macOS, a Proton prefix on Linux, and several more - but any one
machine can only ever be one of those. So this builds fake installs on disk,
tells `platforms` it is running somewhere else, and checks what comes back.

Run it directly: python3 tests/platforms.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beastfly import config as cfg              # noqa: E402
from beastfly import game as game_mod           # noqa: E402
from beastfly import platforms as plat          # noqa: E402

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("ok    %s" % name)
    else:
        FAILED.append(name)
        print("FAIL  %s%s" % (name, ("  - " + detail) if detail else ""))


def equal(name, got, want):
    check(name, _same(got, want), "got %r, wanted %r" % (got, want))


def _same(got, want):
    """Equality that sees through symlinked temp dirs (/var -> /private/var)."""
    if isinstance(got, list) and isinstance(want, list):
        return len(got) == len(want) and all(_same(a, b) for a, b in zip(got, want))
    if isinstance(got, Path) and isinstance(want, Path):
        try:
            return got.resolve() == want.resolve()
        except OSError:
            return got == want
    return got == want


# ------------------------------------------------------------- fixtures

def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def windows_install(folder):
    """A Windows build: the exe, plus the Unity data folder beside it."""
    touch(folder / plat.WINDOWS_EXE)
    (folder / plat.DATA_DIR).mkdir(parents=True, exist_ok=True)
    return folder


def macos_install(folder):
    """A macOS build, which is an .app bundle rather than a single file."""
    (folder / plat.MACOS_APP / "Contents/MacOS").mkdir(parents=True, exist_ok=True)
    return folder


def linux_install(folder, name="Hollow Knight Silksong"):
    """A Linux build: an extensionless binary next to <name>_Data."""
    touch(folder / name)
    (folder / plat.DATA_DIR).mkdir(parents=True, exist_ok=True)
    return folder


def steam_library(root, extra=()):
    """A steamapps folder, with libraryfolders.vdf listing any extra drives."""
    apps = root / "steamapps"
    (apps / "common").mkdir(parents=True, exist_ok=True)
    entries = "\n".join('    "%d" {  "path"  "%s"  }'
                        % (index, str(path).replace("\\", "\\\\"))
                        for index, path in enumerate(extra))
    (apps / "libraryfolders.vdf").write_text('"libraryfolders"\n{\n%s\n}\n' % entries)
    return apps


class Pretend:
    """Run a block as if this were another OS, with a throwaway home folder."""

    def __init__(self, host, home, **patches):
        self.patches = dict(patches, HOST=host, HOME=home)
        self.saved = {}

    def __enter__(self):
        for key, value in self.patches.items():
            self.saved[key] = getattr(plat, key)
            setattr(plat, key, value)
        return self

    def __exit__(self, *_):
        for key, value in self.saved.items():
            setattr(plat, key, value)
        return False


class FakeConf:
    """Just enough of Config for game.launch and saves to work against."""

    def __init__(self, game, wrapper=None, **values):
        self.game = Path(game)
        self.wrapper = Path(wrapper) if wrapper else None
        self.configured = True
        self.values = {"launch_via_wrapper": True, "launch_via_steam": False}
        self.values.update(values)

    def __getitem__(self, key):
        return self.values.get(key)


# ------------------------------------------------------------ detection

def test_build_detection(tmp):
    windows = windows_install(tmp / "builds/win/Hollow Knight Silksong")
    mac = macos_install(tmp / "builds/mac/Hollow Knight Silksong")
    linux = linux_install(tmp / "builds/linux/Hollow Knight Silksong")
    old_linux = linux_install(tmp / "builds/linux-old/Hollow Knight Silksong",
                              name="Hollow Knight Silksong.x86_64")

    equal("windows build detected", plat.build_of(windows), plat.WINDOWS)
    equal("macos build detected", plat.build_of(mac), plat.MACOS)
    equal("linux build detected", plat.build_of(linux), plat.LINUX)
    equal("linux .x86_64 build detected", plat.build_of(old_linux), plat.LINUX)
    equal("empty folder is not an install", plat.build_of(tmp / "builds"), None)

    # The Linux binary and the folder holding it share a name, so a bare folder
    # must not be mistaken for the executable inside it.
    bare = tmp / "bare/Hollow Knight Silksong"
    bare.mkdir(parents=True)
    equal("folder named like the binary is not an install", plat.build_of(bare), None)


def test_windows_host(tmp):
    """Steam on C:, a second library on D:, Xbox, and GOG - all at once."""
    drive_c = tmp / "C"
    drive_d = tmp / "D"
    steam = steam_library(drive_c / "Program Files (x86)/Steam", extra=[drive_d / "SteamLib"])
    steam_library(drive_d / "SteamLib")
    windows_install(steam / "common/Hollow Knight Silksong")
    windows_install(drive_d / "SteamLib/steamapps/common/Hollow Knight Silksong")
    windows_install(drive_c / "GOG Games/Hollow Knight Silksong")
    windows_install(drive_c / "XboxGames/Hollow Knight Silksong/Content")

    home = tmp / "winhome"
    (home / "AppData/LocalLow" / plat.SAVE_FOLDER).mkdir(parents=True)

    with Pretend(plat.WINDOWS, home,
                 _steam_roots=lambda: [drive_c / "Program Files (x86)/Steam"],
                 _drives=lambda: [drive_c, drive_d]):
        os.environ["USERPROFILE"] = str(home)
        found = {str(install["game"]) for install in cfg.find_installs()}
        kinds = {str(i["game"]): i["kind"] for i in cfg.find_installs()}

        check("windows: steam install found",
              str((steam / "common/Hollow Knight Silksong").resolve()) in found)
        check("windows: second steam library found",
              str((drive_d / "SteamLib/steamapps/common/"
                   "Hollow Knight Silksong").resolve()) in found)
        check("windows: gog install found",
              str((drive_c / "GOG Games/Hollow Knight Silksong").resolve()) in found)
        check("windows: xbox Content/ install found",
              str((drive_c / "XboxGames/Hollow Knight Silksong/Content").resolve()) in found)
        equal("windows: steam copy labelled steam",
              kinds.get(str((steam / "common/Hollow Knight Silksong").resolve())), "steam")

        saves = plat.save_candidates(steam / "common/Hollow Knight Silksong")
        equal("windows: saves in AppData/LocalLow", saves[:1],
              [home / "AppData/LocalLow" / plat.SAVE_FOLDER])
        os.environ.pop("USERPROFILE", None)


def test_macos_wrapper(tmp):
    """The original case: a Windows build inside a Porting Kit .app."""
    home = tmp / "machome"
    wrapper = home / "Applications/Silksong.app"
    drive_c = wrapper / "Contents/SharedSupport/prefix/drive_c"
    game = windows_install(drive_c / "GOG Games/Hollow Knight Silksong")
    (drive_c / "users/Wineskin/AppData/LocalLow" / plat.SAVE_FOLDER).mkdir(parents=True)

    with Pretend(plat.MACOS, home,
                 _steam_roots=lambda: [],
                 _app_roots=lambda: [home / "Applications"]):
        installs = cfg.find_installs()
        equal("macos: one install found in the wrapper", len(installs), 1)
        equal("macos: wrapper recorded", installs[0]["wrapper"].name, "Silksong.app")
        equal("macos: windows build behind the wrapper",
              installs[0]["build"], plat.WINDOWS)
        equal("macos: saves found inside the prefix",
              plat.save_candidates(game)[:1],
              [drive_c / "users/Wineskin/AppData/LocalLow" / plat.SAVE_FOLDER])


def test_macos_native(tmp):
    """A Mac Steam install, where BepInEx hooks in through run_bepinex.sh."""
    home = tmp / "machome2"
    steam = steam_library(home / "Library/Application Support/Steam")
    game = macos_install(steam / "common/Hollow Knight Silksong")
    support = home / "Library/Application Support"
    (support / "unity.Team Cherry.Hollow Knight Silksong").mkdir(parents=True)

    with Pretend(plat.MACOS, home,
                 _steam_roots=lambda: [home / "Library/Application Support/Steam"],
                 _app_roots=lambda: []):
        installs = cfg.find_installs()
        equal("macos native: install found", len(installs), 1)
        equal("macos native: macos build", installs[0]["build"], plat.MACOS)
        equal("macos native: saves in Application Support",
              plat.save_candidates(game)[:1],
              [support / "unity.Team Cherry.Hollow Knight Silksong"])


def test_linux_native(tmp):
    home = tmp / "linhome"
    steam = steam_library(home / ".local/share/Steam")
    game = linux_install(steam / "common/Hollow Knight Silksong")
    (home / ".config/unity3d" / plat.SAVE_FOLDER).mkdir(parents=True)

    with Pretend(plat.LINUX, home,
                 _steam_roots=lambda: [home / ".local/share/Steam"]):
        installs = cfg.find_installs()
        equal("linux native: install found", len(installs), 1)
        equal("linux native: linux build", installs[0]["build"], plat.LINUX)
        equal("linux native: saves in ~/.config/unity3d",
              plat.save_candidates(game)[:1],
              [home / ".config/unity3d" / plat.SAVE_FOLDER])


def test_linux_proton(tmp):
    """A Windows build on Linux: game in common/, saves in compatdata/."""
    home = tmp / "protonhome"
    steam = steam_library(home / ".local/share/Steam")
    game = windows_install(steam / "common/Hollow Knight Silksong")
    prefix = (steam / "compatdata" / plat.STEAM_APP_ID / "pfx/drive_c")
    (prefix / "users/steamuser/AppData/LocalLow" / plat.SAVE_FOLDER).mkdir(parents=True)

    with Pretend(plat.LINUX, home,
                 _steam_roots=lambda: [home / ".local/share/Steam"]):
        installs = cfg.find_installs()
        equal("proton: install found", len(installs), 1)
        equal("proton: windows build", installs[0]["build"], plat.WINDOWS)
        equal("proton: saves found in the compatdata prefix",
              plat.save_candidates(game)[:1],
              [prefix / "users/steamuser/AppData/LocalLow" / plat.SAVE_FOLDER])


def test_linux_wine_prefix(tmp):
    """A GOG copy in a bare ~/.wine, with no launcher wrapped around it."""
    home = tmp / "winehome"
    drive_c = home / ".wine/drive_c"
    game = windows_install(drive_c / "GOG Games/Hollow Knight Silksong")
    (drive_c / "users/player/AppData/LocalLow" / plat.SAVE_FOLDER).mkdir(parents=True)

    with Pretend(plat.LINUX, home, _steam_roots=lambda: []):
        installs = cfg.find_installs()
        equal("wine: install found", len(installs), 1)
        equal("wine: no wrapper to launch through", installs[0]["wrapper"], None)
        equal("wine: saves found inside the prefix",
              plat.save_candidates(game)[:1],
              [drive_c / "users/player/AppData/LocalLow" / plat.SAVE_FOLDER])


# -------------------------------------------------------------- launching

def spy():
    """Stand in for plat.spawn and record the command it was handed."""
    calls = []

    def record(command, cwd=None, env=None):
        calls.append({"command": [str(c) for c in command],
                      "cwd": str(cwd) if cwd else None, "env": env})
    return calls, record


def test_launch(tmp):
    home = tmp / "launchhome"

    # 1. Windows build on Windows: run the exe, doorstop rides along in winhttp.
    game = windows_install(home / "Games/Hollow Knight Silksong")
    calls, record = spy()
    with Pretend(plat.WINDOWS, home, spawn=record):
        how = game_mod.launch(FakeConf(game))
    check("launch: windows runs the exe directly",
          calls and calls[0]["command"][0].endswith(plat.WINDOWS_EXE), str(calls))
    check("launch: windows reports the build", "windows" in how.lower(), how)

    # 2. Linux build with BepInEx: the loader script, not the binary.
    linux_game = linux_install(home / "Games/linux/Hollow Knight Silksong")
    script = linux_game / "run_bepinex.sh"
    script.write_text("#!/bin/sh\n")
    calls, record = spy()
    with Pretend(plat.LINUX, home, spawn=record):
        how = game_mod.launch(FakeConf(linux_game))
    check("launch: linux goes through run_bepinex.sh",
          calls and calls[0]["command"][1].endswith("run_bepinex.sh"), str(calls))
    check("launch: linux passes the binary name to the script",
          calls and calls[0]["command"][2] == "Hollow Knight Silksong", str(calls))
    check("launch: linux says mods are loaded", "mods loaded" in how, how)
    check("launch: run_bepinex.sh was made executable",
          os.access(str(script), os.X_OK))

    # 3. Native build with no loader yet: start the game anyway.
    plain = linux_install(home / "Games/plain/Hollow Knight Silksong")
    calls, record = spy()
    with Pretend(plat.LINUX, home, spawn=record):
        game_mod.launch(FakeConf(plain))
    check("launch: linux without BepInEx runs the binary",
          calls and calls[0]["command"][0].endswith("Hollow Knight Silksong"), str(calls))

    # 4. macOS build with BepInEx: the script too, not `open`, or the .app
    #    starts without the doorstop environment and mods never load.
    mac_game = macos_install(home / "Games/mac/Hollow Knight Silksong")
    (mac_game / "run_bepinex.sh").write_text("#!/bin/sh\n")
    calls, record = spy()
    with Pretend(plat.MACOS, home, spawn=record, opener=lambda: ["open"]):
        how = game_mod.launch(FakeConf(mac_game))
    check("launch: macos native prefers run_bepinex.sh over open",
          calls and calls[0]["command"][1].endswith("run_bepinex.sh"), str(calls))
    check("launch: macos passes the .app name to the script",
          calls and calls[0]["command"][2] == plat.MACOS_APP, str(calls))
    check("launch: macos native says mods are loaded", "mods loaded" in how, how)

    # 5. macOS build with no loader: fall back to opening the bundle.
    bare_mac = macos_install(home / "Games/macbare/Hollow Knight Silksong")
    calls, record = spy()
    with Pretend(plat.MACOS, home, spawn=record, opener=lambda: ["open"]):
        game_mod.launch(FakeConf(bare_mac))
    check("launch: macos without BepInEx opens the .app",
          calls and calls[0]["command"] == ["open", str(bare_mac / plat.MACOS_APP)],
          str(calls))

    # 6. Windows build on Linux with wine on PATH.
    wine_game = windows_install(home / ".wine/drive_c/GOG Games/Hollow Knight Silksong")
    calls, record = spy()
    with Pretend(plat.LINUX, home, spawn=record, wine_command=lambda: "/usr/bin/wine"):
        how = game_mod.launch(FakeConf(wine_game))
    check("launch: windows build on linux uses wine",
          calls and calls[0]["command"][0] == "/usr/bin/wine", str(calls))
    equal("launch: WINEPREFIX points at the prefix root",
          calls[0]["env"].get("WINEPREFIX") if calls else None,
          str(home / ".wine"))

    # 7. Windows build on Linux with nothing to run it: say so, don't pretend.
    calls, record = spy()
    with Pretend(plat.LINUX, home, spawn=record, wine_command=lambda: None,
                 steam_command=lambda app_id=None: None):
        try:
            game_mod.launch(FakeConf(wine_game))
            check("launch: unrunnable windows build raises", False, "no error raised")
        except game_mod.LaunchError as error:
            check("launch: unrunnable windows build explains itself",
                  "Wine" in str(error), str(error))

    # 8. macOS wrapper: hand the .app to `open`, exactly like double-clicking.
    wrapper = home / "Applications/Silksong.app"
    wrapped = windows_install(
        wrapper / "Contents/SharedSupport/prefix/drive_c/GOG Games/Hollow Knight Silksong")
    calls, record = spy()
    with Pretend(plat.MACOS, home, spawn=record, opener=lambda: ["open"]):
        how = game_mod.launch(FakeConf(wrapped, wrapper=wrapper))
    equal("launch: macos opens the wrapper",
          calls[0]["command"] if calls else None, ["open", str(wrapper)])
    equal("launch: macos reports the wrapper name", how, "Silksong.app")

    # 9. Steam launch options: the one thing Beastfly can only tell you about.
    conf = FakeConf(linux_game)
    with Pretend(plat.LINUX, home):
        options = game_mod.steam_launch_options(conf)
    check("launch: steam launch options quote the script",
          options == '"%s" %%command%%' % script, str(options))


def test_vdf_parsing(tmp):
    """libraryfolders.vdf is where a second drive's games are hiding."""
    home = tmp / "vdfhome"
    root = home / "Steam"
    other = tmp / "Elsewhere"
    steam_library(root, extra=[other])
    steam_library(other)
    with Pretend(plat.LINUX, home, _steam_roots=lambda: [root]):
        libraries = [str(path) for path in plat.steam_libraries()]
    check("vdf: the home library is listed",
          str((root / "steamapps").resolve()) in libraries, str(libraries))
    check("vdf: the extra library is listed",
          str((other / "steamapps").resolve()) in libraries, str(libraries))


def main():
    with tempfile.TemporaryDirectory(prefix="beastfly-platforms-") as scratch:
        tmp = Path(scratch)
        for test in (test_build_detection, test_windows_host, test_macos_wrapper,
                     test_macos_native, test_linux_native, test_linux_proton,
                     test_linux_wine_prefix, test_launch, test_vdf_parsing):
            test(tmp)
    print("------------------------------")
    if FAILED:
        print("%d of %d failed" % (len(FAILED), len(FAILED) + len(PASSED)))
        return 1
    print("all %d checks passed" % len(PASSED))
    return 0


if __name__ == "__main__":
    sys.exit(main())
