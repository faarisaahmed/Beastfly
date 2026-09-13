"""Persistent settings and game-path discovery.

State lives in ~/.beastfly so it survives reinstalling or moving the game
wrapper. Nothing here writes into the game folder.

Everything that depends on which operating system, store or compatibility
layer is in play is delegated to `platforms`; this module only decides what
counts as an install and remembers what the user picked.
"""

import json
import os
from pathlib import Path

from . import platforms as plat

HOME = Path.home()
STATE_DIR = Path(os.environ.get("BEASTFLY_HOME", HOME / ".beastfly"))
CONFIG_FILE = STATE_DIR / "config.json"
CACHE_DIR = STATE_DIR / "cache"
BACKUP_DIR = STATE_DIR / "backups"

# Re-exported so callers can keep saying cfg.GAME_EXE.
GAME_DIR_NAMES = plat.GAME_DIR_NAMES
GAME_EXE = plat.WINDOWS_EXE

DEFAULTS = {
    # INSTALLATION
    "auto_install_deps": True,
    "auto_enable_new": True,
    "confirm_remove": True,
    # UPDATES
    "check_updates": True,
    "auto_update": False,
    # PROFILES
    "remember_profile": True,
    # GAME
    "launch_via_wrapper": True,
    "launch_via_steam": False,
    "confirm_launch": False,
    "backup_saves_on_launch": True,
    # DISPLAY
    "show_deps": True,
    "show_update_notifications": True,
    # PATHS
    "game_path": "",        # .../Hollow Knight Silksong (holds the executable)
    "bepinex_path": "",     # defaults to <game_path>/BepInEx
    "downloads_path": str(HOME / "Downloads"),
    "wrapper_path": "",     # the Wine wrapper .app used to launch, if any
    # INTEGRATIONS
    "thunderstore_community": "hollow-knight-silksong",
    "nexus_api_key": "",
    "nexus_game_slug": "hollowknightsilksong",
}


class Config:
    def __init__(self):
        self.values = dict(DEFAULTS)
        self.load()

    # ---------- persistence ----------

    def load(self):
        if CONFIG_FILE.exists():
            try:
                stored = json.loads(CONFIG_FILE.read_text())
            except (ValueError, OSError):
                stored = {}
            for key, value in stored.items():
                if key in DEFAULTS:
                    self.values[key] = value
            # Beastfly used to be macOS-only and called this setting after the
            # one wrapper it knew about. Carry the old answer across.
            if "launch_via_wrapper" not in stored and "launch_via_porting_kit" in stored:
                self.values["launch_via_wrapper"] = bool(stored["launch_via_porting_kit"])

    def save(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.values, indent=2, sort_keys=True))
        tmp.replace(CONFIG_FILE)

    def reset(self):
        keep = {"game_path", "bepinex_path", "wrapper_path", "nexus_api_key"}
        for key, value in DEFAULTS.items():
            if key not in keep:
                self.values[key] = value
        self.save()

    # ---------- access ----------

    def __getitem__(self, key):
        return self.values.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.values[key] = value
        self.save()

    def toggle(self, key):
        self[key] = not bool(self[key])
        return self[key]

    @property
    def configured(self):
        return bool(self["game_path"]) and Path(self["game_path"]).is_dir()

    # ---------- derived paths ----------

    @property
    def game(self):
        return Path(self["game_path"]) if self["game_path"] else None

    @property
    def bepinex(self):
        if self["bepinex_path"]:
            return Path(self["bepinex_path"])
        return self.game / "BepInEx" if self.game else None

    @property
    def plugins(self):
        return self.bepinex / "plugins" if self.bepinex else None

    @property
    def downloads(self):
        return Path(self["downloads_path"]).expanduser()

    @property
    def wrapper(self):
        return Path(self["wrapper_path"]) if self["wrapper_path"] else None

    @property
    def bepinex_installed(self):
        return bool(self.bepinex and (self.bepinex / "core" / "BepInEx.dll").exists())


# ---------- discovery ----------

# Short local names for the error-swallowing filesystem helpers; the real
# definitions live in platforms, next to everything else that touches disk.
_is_dir = plat.is_dir
_exists = plat.exists
_listdir = plat.listdir


def _rank(install):
    """Sort key: what the person in front of this machine most likely plays.

    A build that runs natively beats one behind a compatibility layer, and a
    wrapper we know how to launch beats a bare prefix we can only guess at.
    """
    build_rank = 0 if plat.runs_natively(install["build"]) else 1
    wrapper_rank = 0 if install["wrapper"] else 1
    return (build_rank, wrapper_rank, str(install["game"]))


def find_installs():
    """Locate Silksong installs.

    Returns [{game, wrapper, kind, build}] best-first, covering native builds
    from every store plus Windows builds inside any Wine prefix we can find.
    """
    found = []
    seen = set()

    def add(game_dir, wrapper, kind):
        try:
            game_dir = game_dir.resolve()
        except OSError:
            return
        if game_dir in seen:
            return
        _, build = plat.executable(game_dir)
        if build is None:
            return
        seen.add(game_dir)
        found.append({"game": game_dir, "wrapper": wrapper, "kind": kind,
                      "build": build})

    def scan(root, wrapper, kind):
        """Try `root` itself and the usual folder names underneath it."""
        add(root, wrapper, kind)
        for name in plat.GAME_DIR_NAMES:
            base = root / name
            if not _is_dir(base):
                continue
            add(base, wrapper, kind)
            # Xbox installs nest the real files one level further down, and GOG's
            # Linux installers use a game/ subfolder.
            for nested in ("Content", "game"):
                add(base / nested, wrapper, kind)

    # Native builds: Steam libraries on any drive, plus the per-platform spots.
    for root, store in plat.native_roots():
        scan(root, None, store)

    # Windows builds inside a Wine prefix: Porting Kit, Whisky, CrossOver,
    # Proton, Lutris, Heroic, Bottles, or a bare ~/.wine.
    for drive_c, wrapper, kind in plat.wine_prefixes():
        for store in plat.WINDOWS_STORE_DIRS:
            store_dir = drive_c / store
            if _is_dir(store_dir):
                scan(store_dir, wrapper, kind)

    found.sort(key=_rank)
    return found


def describe_install(install):
    """A short 'steam · windows build' line for the install picker."""
    build = install.get("build")
    words = [install.get("kind") or "install"]
    if build and not plat.runs_natively(build):
        words.append("%s build" % {plat.WINDOWS: "Windows", plat.MACOS: "macOS",
                                   plat.LINUX: "Linux"}.get(build, build))
    return " · ".join(words)


# Writing a BepInEx tree into one of these would scatter loader files across a
# folder full of unrelated things, so setup says something first.
SHARED_FOLDERS = (Path("/Applications"), HOME / "Applications", HOME / "Desktop",
                  HOME / "Downloads", HOME, Path("/"))


def is_shared_folder(path):
    """True if `path` is a folder full of other things, not a game folder."""
    if path is None:
        return False
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    for shared in SHARED_FOLDERS:
        try:
            if resolved == shared.resolve():
                return True
        except OSError:
            continue
    return False


def wrapper_for(game_path):
    """Walk up from a game folder to the .app wrapper that contains it."""
    if game_path is None:
        return None
    for parent in Path(game_path).parents:
        if parent.name.endswith(".app"):
            return parent
    return None


# ---------- BepInEx discovery ----------

BEPINEX_MARKER = "core/BepInEx.dll"


def _is_bepinex(path):
    return _exists(path / BEPINEX_MARKER)


def find_bepinex(game_dir, deep=True):
    """Locate BepInEx trees for an install. Returns [(path, kind)] best-first.

    Usually it sits next to the exe, but not always: Xbox installs nest the
    game under Content/, and r2modman-style managers keep a separate tree per
    profile. Guessing <game>/BepInEx and stopping there is what makes people
    type paths by hand.
    """
    found = []
    seen = set()

    def add(path, kind):
        if path is None:
            return
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved in seen or not _is_bepinex(resolved):
            return
        seen.add(resolved)
        found.append((resolved, kind))

    if game_dir is not None:
        game_dir = Path(game_dir)
        add(game_dir / "BepInEx", "next to the game")
        add(game_dir / "Content" / "BepInEx", "under Content/")
        # Some layouts put the exe in a subfolder of the install root.
        for parent in list(game_dir.parents)[:2]:
            add(parent / "BepInEx", "one level up")

        # Anywhere inside the same Wine prefix.
        if deep:
            prefix = plat.prefix_of(game_dir)
            if prefix is not None:
                for marker in _bounded_glob(prefix, "BepInEx", 6):
                    add(marker, "elsewhere in the prefix")

    # Trees maintained by another mod manager.
    for root in plat.manager_roots():
        if not _is_dir(root):
            continue
        for marker in _bounded_glob(root, "BepInEx", 5):
            add(marker, "another mod manager's profile")

    return found


def _bounded_glob(root, name, depth):
    """Directories called `name` within `depth` levels of `root`.

    Hand-rolled rather than rglob so a deep prefix can't stall discovery.
    """
    out = []
    frontier = [(root, 0)]
    while frontier and len(out) < 40:
        current, level = frontier.pop()
        if level > depth:
            continue
        for entry in _listdir(current):
            if not _is_dir(entry):
                continue
            if entry.name == name:
                out.append(entry)
                continue
            if entry.name.endswith(".app") or entry.name.startswith("."):
                continue
            frontier.append((entry, level + 1))
    return out
