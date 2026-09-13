"""Where Silksong lives, and how to start it, on each machine it runs on.

Silksong ships native builds for Windows, macOS and Linux, and people buy it
from Steam, GOG, the Xbox app and Epic. On top of that the Windows build gets
run on macOS through Porting Kit, Whisky and CrossOver, and on Linux through
Proton, Lutris, Heroic and Bottles. The mod tree is identical in every one of
those cases - BepInEx's Silksong pack carries winhttp.dll, libdoorstop.so and
libdoorstop.dylib side by side - so the only things that actually differ are
paths and the command used to start the game.

All of that lives here, so config, saves and launching can stay platform-blind.
"""

import os
import re
import shutil
import string
import subprocess
import sys
from pathlib import Path

HOME = Path.home()

WINDOWS = "windows"
MACOS = "macos"
LINUX = "linux"


def _host():
    if sys.platform.startswith("win") or os.name == "nt":
        return WINDOWS
    if sys.platform == "darwin":
        return MACOS
    return LINUX          # anything else is close enough to Linux to try


HOST = _host()
HOST_LABEL = {WINDOWS: "Windows", MACOS: "macOS", LINUX: "Linux"}[HOST]

# Silksong's Steam app id, taken from the steam_appid.txt in BepInEx's own
# Silksong pack. Used to find Proton prefixes and to hand the game to Steam.
STEAM_APP_ID = "1030300"

# The install folder, whichever store it came from. Xbox nests the real files
# one more level down in Content/.
GAME_DIR_NAMES = ("Hollow Knight Silksong", "Hollow Knight Silksong Content",
                  "Hollow Knight Silksong Demo", "Silksong")

WINDOWS_EXE = "Hollow Knight Silksong.exe"
MACOS_APP = "Hollow Knight Silksong.app"
# Unity's Linux player keeps the plain name; .x86_64 shows up on older builds.
LINUX_BINARIES = ("Hollow Knight Silksong", "Hollow Knight Silksong.x86_64")
# Every Unity build has this beside its executable, which is what tells a Linux
# binary apart from the folder of the same name that contains it.
DATA_DIR = "Hollow Knight Silksong_Data"


# ------------------------------------------------------------ filesystem

def is_dir(path):
    """is_dir() that shrugs off the unreadable corners of /Applications."""
    try:
        return path.is_dir()
    except OSError:
        return False


def is_file(path):
    try:
        return path.is_file()
    except OSError:
        return False


def exists(path):
    try:
        return path.exists()
    except OSError:
        return False


def listdir(path):
    try:
        return list(path.iterdir())
    except OSError:
        return []


def children(path, limit=400):
    """Immediate subdirectories, capped so a huge folder can't stall a scan."""
    return [p for p in listdir(path)[:limit] if is_dir(p)]


# ------------------------------------------------------- build detection

def executable(game_dir):
    """The thing you actually run in `game_dir`, as (path, build).

    `build` is the platform the *game* was compiled for, which is not always
    the platform you are on: a Mac running Porting Kit has a Windows build.
    Returns (None, None) when the folder holds no Silksong at all.
    """
    if game_dir is None:
        return None, None
    game_dir = Path(game_dir)

    exe = game_dir / WINDOWS_EXE
    if is_file(exe):
        return exe, WINDOWS

    app = game_dir / MACOS_APP
    if is_dir(app):
        return app, MACOS

    if is_dir(game_dir / DATA_DIR):
        for name in LINUX_BINARIES:
            binary = game_dir / name
            if is_file(binary):
                return binary, LINUX

    return None, None


def build_of(game_dir):
    return executable(game_dir)[1]


def holds_game(game_dir):
    return executable(game_dir)[0] is not None


def runs_natively(build):
    """True if this machine can start that build without a compatibility layer."""
    return build == HOST


def prefix_of(path):
    """The drive_c a path sits inside, or None if it isn't in a Wine prefix."""
    if path is None:
        return None
    for parent in [Path(path)] + list(Path(path).parents):
        if parent.name == "drive_c":
            return parent
    return None


# ------------------------------------------------------------ Steam

_VDF_PATH = re.compile(r'"path"\s*"([^"]+)"')


def _steam_roots():
    if HOST == WINDOWS:
        roots = [_program_files("Steam"), _program_files("Steam", x86=False),
                 Path("C:/Steam")]
    elif HOST == MACOS:
        roots = [HOME / "Library/Application Support/Steam"]
    else:
        roots = [
            HOME / ".steam/steam",
            HOME / ".steam/root",
            HOME / ".local/share/Steam",
            # Flatpak keeps its own copy of everything under ~/.var.
            HOME / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
            HOME / "snap/steam/common/.local/share/Steam",
        ]
    return [r for r in roots if r is not None and is_dir(r)]


def steam_libraries():
    """Every steamapps folder Steam knows about, including extra drives.

    Steam records additional libraries in libraryfolders.vdf. Parsing it is the
    difference between finding a game on D: and telling the user we looked.
    """
    found, seen = [], set()

    def add(apps):
        try:
            resolved = apps.resolve()
        except OSError:
            return
        if resolved in seen or not is_dir(resolved):
            return
        seen.add(resolved)
        found.append(resolved)

    for root in _steam_roots():
        apps = root / "steamapps"
        add(apps)
        manifest = apps / "libraryfolders.vdf"
        try:
            text = manifest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in _VDF_PATH.findall(text):
            # VDF escapes backslashes, so "D:\\Games" comes through doubled.
            add(Path(raw.replace("\\\\", "\\")) / "steamapps")
    return found


def proton_prefixes():
    """drive_c folders Proton made for Silksong, newest library first."""
    out = []
    for library in steam_libraries():
        drive_c = library / "compatdata" / STEAM_APP_ID / "pfx" / "drive_c"
        if is_dir(drive_c):
            out.append(drive_c)
    return out


# ------------------------------------------------------- native installs

def _program_files(*parts, **kwargs):
    """A path under Program Files, honouring the env vars Windows sets."""
    if kwargs.get("x86", True):
        base = os.environ.get("ProgramFiles(x86)") or "C:/Program Files (x86)"
    else:
        base = os.environ.get("ProgramFiles") or "C:/Program Files"
    return Path(base).joinpath(*parts)


def _drives():
    """Drive roots that exist, so C:, D: and an external E: all get searched."""
    if HOST != WINDOWS:
        return []
    # A: and B: are the floppy letters; probing them can spin up a card
    # reader and, on an empty drive, pop a "no disk" dialog.
    return [Path("%s:/" % letter) for letter in string.ascii_uppercase[2:]
            if is_dir(Path("%s:/" % letter))]


# Store layouts inside a Windows filesystem - a real one, or a Wine drive_c.
WINDOWS_STORE_DIRS = (
    "GOG Games",
    "Program Files (x86)/Steam/steamapps/common",
    "Program Files/Steam/steamapps/common",
    "SteamLibrary/steamapps/common",
    "Steam/steamapps/common",
    "Games",
    "XboxGames",
    "Program Files/Epic Games",
    "Program Files (x86)/Epic Games",
    "Program Files (x86)/GOG Galaxy/Games",
    "Program Files/GOG Galaxy/Games",
    "Program Files",
    "Program Files (x86)",
)


def windows_roots():
    """(folder, store) pairs to look for a Windows install under `folder`."""
    out = []
    for drive in _drives():
        for store in WINDOWS_STORE_DIRS:
            candidate = drive / store
            if is_dir(candidate):
                out.append((candidate, _store_name(store)))
    return out


def _store_name(store):
    lowered = store.lower()
    if "steam" in lowered:
        return "steam"
    if "gog" in lowered:
        return "gog"
    if "xbox" in lowered:
        return "xbox"
    if "epic" in lowered:
        return "epic"
    return "installed"


def native_roots():
    """(folder, store) pairs that hold native builds for this platform."""
    out = [(library / "common", "steam") for library in steam_libraries()]

    if HOST == MACOS:
        out += [(HOME / "Applications", "installed"),
                (Path("/Applications"), "installed"),
                (HOME / "Games", "installed"),
                (HOME / "Library/Application Support/GOG.com", "gog")]
    elif HOST == LINUX:
        out += [(HOME / "GOG Games", "gog"),
                (HOME / "Games", "installed"),
                (HOME / "Games/Heroic", "gog"),
                (HOME / ".itch/apps", "itch")]
    elif HOST == WINDOWS:
        out += windows_roots()

    return [(root, store) for root, store in out if is_dir(root)]


# --------------------------------------------------------- Wine prefixes

def _glob_prefixes(root, tail="drive_c", depth=1):
    """drive_c folders `depth` levels under `root`."""
    out = []
    if not is_dir(root):
        return out
    frontier = [(root, 0)]
    while frontier:
        current, level = frontier.pop()
        candidate = current / tail
        if is_dir(candidate):
            out.append(candidate)
        if level < depth:
            for child in children(current, limit=60):
                frontier.append((child, level + 1))
    return out


def _app_roots():
    """Folders where a Wineskin/Porting Kit .app plausibly sits."""
    return [HOME / "Applications", Path("/Applications"), HOME / "Downloads",
            HOME / "Games", HOME / "Library/Application Support/Porting Kit",
            HOME / "Desktop"]


def _app_prefixes(app):
    """drive_c locations for Wineskin, CrossOver and Whisky style wrappers."""
    return [app / "Contents/SharedSupport/prefix/drive_c",
            app / "Contents/drive_c",
            app / "drive_c"]


def wine_prefixes():
    """Every Wine prefix worth searching, as (drive_c, wrapper, kind).

    `wrapper` is the .app to open when launching, when there is one. `kind`
    names the tool so the install list can say where a copy came from.
    """
    out, seen = [], set()

    def add(drive_c, wrapper, kind):
        if not is_dir(drive_c):
            return
        try:
            resolved = drive_c.resolve()
        except OSError:
            return
        if resolved in seen:
            return
        seen.add(resolved)
        out.append((resolved, wrapper, kind))

    if HOST == MACOS:
        for root in _app_roots():
            for entry in listdir(root):
                if entry.name.endswith(".app"):
                    for drive_c in _app_prefixes(entry):
                        add(drive_c, entry, "porting-kit")
                elif is_dir(entry / "drive_c"):
                    add(entry / "drive_c", None, "wine-prefix")
        for bottles in (HOME / "Library/Application Support/CrossOver/Bottles",
                        HOME / "Library/Containers/com.codeweavers.CrossOver"
                               "/Data/Library/Application Support/CrossOver/Bottles"):
            for bottle in children(bottles):
                add(bottle / "drive_c", None, "crossover")
        whisky = (HOME / "Library/Containers/com.isaacmarovitz.Whisky/Bottles")
        for bottle in children(whisky):
            add(bottle / "drive_c", None, "whisky")

    elif HOST == LINUX:
        add(HOME / ".wine/drive_c", None, "wine-prefix")
        for root in (HOME / ".local/share/wineprefixes",
                     HOME / "Games",
                     HOME / ".local/share/lutris/runners/winesteam/prefix"):
            for drive_c in _glob_prefixes(root, depth=1):
                add(drive_c, None, "wine-prefix")
        # Heroic and Bottles each bury the prefix a level or two down.
        for root in (HOME / "Games/Heroic/Prefixes",
                     HOME / ".var/app/com.heroicgameslauncher.hgl/config/heroic/Prefixes"):
            for drive_c in _glob_prefixes(root, tail="pfx/drive_c", depth=2):
                add(drive_c, None, "heroic")
        for root in (HOME / ".local/share/bottles/bottles",
                     HOME / ".var/app/com.usebottles.bottles/data/bottles/bottles"):
            for drive_c in _glob_prefixes(root, depth=1):
                add(drive_c, None, "bottles")
        for drive_c in proton_prefixes():
            add(drive_c, None, "proton")

    return out


# --------------------------------------------------------------- saves

# Unity writes to <persistentDataPath>, which is spelt differently everywhere.
SAVE_FOLDER = "Team Cherry/Hollow Knight Silksong"


def save_candidates(game_dir):
    """Places this install's saves could be, best guess first.

    A Windows build keeps them inside whichever prefix runs it, so the prefix
    around the game is checked before anything on the host.
    """
    out = []

    drive_c = prefix_of(game_dir)
    prefixes = [drive_c] if drive_c else []
    # A Windows build in a Steam library is Proton's: the game sits in
    # steamapps/common but its saves land in steamapps/compatdata.
    if build_of(game_dir) == WINDOWS and HOST != WINDOWS:
        prefixes += proton_prefixes()
    for prefix in prefixes:
        out += _prefix_saves(prefix)

    if HOST == WINDOWS:
        profile = Path(os.environ.get("USERPROFILE") or HOME)
        out.append(profile / "AppData/LocalLow" / SAVE_FOLDER)
    elif HOST == MACOS:
        support = HOME / "Library/Application Support"
        # Unity used unity.<company>.<product> before switching to nested
        # folders, and which one you get depends on the engine version.
        out.append(support / "unity.Team Cherry.Hollow Knight Silksong")
        out.append(support / SAVE_FOLDER)
    else:
        out.append(HOME / ".config/unity3d" / SAVE_FOLDER)
        out.append(HOME / ".var/app/com.valvesoftware.Steam/.config/unity3d" / SAVE_FOLDER)

    return [path for path in out if is_dir(path)]


def _prefix_saves(drive_c):
    """AppData/LocalLow saves for every user inside a Wine prefix."""
    out = []
    users = drive_c / "users"
    if not is_dir(users):
        return out
    for user in sorted(listdir(users)):
        if user.name in ("Public", "public"):
            continue
        candidate = user / "AppData/LocalLow" / SAVE_FOLDER
        if is_dir(candidate):
            out.append(candidate)
    return out


# -------------------------------------------------------- other managers

def manager_roots():
    """Where r2modman-style managers keep their own BepInEx trees."""
    if HOST == WINDOWS:
        appdata = Path(os.environ.get("APPDATA") or (HOME / "AppData/Roaming"))
        return [appdata / "r2modmanPlus-local",
                appdata / "ThunderstoreModManager",
                Path(os.environ.get("LOCALAPPDATA") or (HOME / "AppData/Local"))
                / "cogfly"]
    if HOST == MACOS:
        support = HOME / "Library/Application Support"
        return [support / "r2modmanPlus-local",
                support / "ThunderstoreModManager",
                support / "cogfly",
                HOME / ".cogfly"]
    return [HOME / ".config/r2modmanPlus-local",
            HOME / ".config/ThunderstoreModManager",
            HOME / ".config/cogfly",
            HOME / ".cogfly"]


# ------------------------------------------------------------ processes

def game_is_running():
    """True if a Silksong process (or the wrapper running it) is already up."""
    if HOST == WINDOWS:
        command = ["tasklist", "/fo", "csv", "/nh"]
    else:
        command = ["ps", "-A", "-o", "command"]
    try:
        output = subprocess.run(command, capture_output=True, text=True,
                                timeout=10).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return False
    for line in output.split("\n"):
        if "silksong" in line and "beastfly" not in line and "tasklist" not in line \
                and "ps -a" not in line:
            return True
    return False


def spawn(command, cwd=None, env=None):
    """Start a detached process, letting it outlive this shell."""
    options = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if cwd is not None:
        options["cwd"] = str(cwd)
    if env is not None:
        options["env"] = env
    if HOST == WINDOWS:
        # Without this the game dies with the terminal it was started from.
        options["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        options["start_new_session"] = True
    subprocess.Popen([str(part) for part in command], **options)


def opener():
    """The command that hands a path to the desktop, or None if there isn't one."""
    if HOST == MACOS:
        return ["open"] if shutil.which("open") else None
    if HOST == WINDOWS:
        return ["cmd", "/c", "start", ""]
    for candidate in ("xdg-open", "gio"):
        if shutil.which(candidate):
            return [candidate, "open"] if candidate == "gio" else [candidate]
    return None


def steam_command(app_id=STEAM_APP_ID):
    """How to ask Steam to launch the game, or None if Steam isn't installed."""
    if shutil.which("steam"):
        return ["steam", "-applaunch", app_id]
    if HOST == MACOS:
        steam_app = Path("/Applications/Steam.app")
        if is_dir(steam_app) and shutil.which("open"):
            return ["open", "steam://rungameid/%s" % app_id]
    if HOST == WINDOWS:
        exe = _program_files("Steam", "steam.exe")
        if is_file(exe):
            return [str(exe), "-applaunch", app_id]
    launcher = opener()
    if launcher and HOST == LINUX:
        return launcher + ["steam://rungameid/%s" % app_id]
    return None


def wine_command():
    """The wine binary to run a Windows exe with, if one is on PATH."""
    for candidate in ("wine64", "wine"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def make_executable(path):
    """chmod +x, ignoring platforms and filesystems where that means nothing."""
    try:
        mode = path.stat().st_mode
        path.chmod(mode | 0o111)
        return True
    except OSError:
        return False
