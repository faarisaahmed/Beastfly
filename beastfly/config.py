"""Persistent settings and game-path discovery.

State lives in ~/.beastfly so it survives reinstalling or moving the game
wrapper. Nothing here writes into the game folder.
"""

import json
import os
from pathlib import Path

HOME = Path.home()
STATE_DIR = Path(os.environ.get("BEASTFLY_HOME", HOME / ".beastfly"))
CONFIG_FILE = STATE_DIR / "config.json"
CACHE_DIR = STATE_DIR / "cache"
BACKUP_DIR = STATE_DIR / "backups"

# Silksong's folder name inside a Windows install, whichever store it came from.
GAME_DIR_NAMES = ("Hollow Knight Silksong", "Hollow Knight Silksong Content")
GAME_EXE = "Hollow Knight Silksong.exe"

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
    "launch_via_porting_kit": True,
    "confirm_launch": False,
    "backup_saves_on_launch": True,
    # DISPLAY
    "show_deps": True,
    "show_update_notifications": True,
    # PATHS
    "game_path": "",        # .../Hollow Knight Silksong  (contains the .exe)
    "bepinex_path": "",     # defaults to <game_path>/BepInEx
    "downloads_path": str(HOME / "Downloads"),
    "wrapper_path": "",     # the Porting Kit / Wineskin .app used to launch
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

def _is_dir(path):
    """is_dir() that shrugs off the unreadable corners of /Applications."""
    try:
        return path.is_dir()
    except OSError:
        return False


def _exists(path):
    try:
        return path.exists()
    except OSError:
        return False


def _listdir(path):
    try:
        return list(path.iterdir())
    except OSError:
        return []


def _search_roots():
    """Places a Windows Silksong install plausibly lives on a Mac."""
    roots = [
        HOME / "Downloads",
        HOME / "Applications",
        Path("/Applications"),
        HOME / "Library/Application Support/Porting Kit",
        HOME / "Games",
    ]
    return [r for r in roots if _is_dir(r)]


def _prefix_candidates(app):
    """drive_c locations for Wineskin, CrossOver and Whisky style wrappers."""
    return [
        app / "Contents/SharedSupport/prefix/drive_c",
        app / "Contents/drive_c",
        app / "drive_c",
    ]


def find_installs():
    """Locate Silksong installs. Returns [{game, wrapper, kind}] best-first."""
    found = []
    seen = set()

    def add(game_dir, wrapper, kind):
        try:
            game_dir = game_dir.resolve()
        except OSError:
            return
        if game_dir in seen or not _exists(game_dir / GAME_EXE):
            return
        seen.add(game_dir)
        found.append({"game": game_dir, "wrapper": wrapper, "kind": kind})

    # Wine-style wrappers: look inside each .app's drive_c.
    for root in _search_roots():
        for app in _listdir(root):
            if not app.name.endswith(".app"):
                continue
            for drive_c in _prefix_candidates(app):
                if not _is_dir(drive_c):
                    continue
                for store in ("GOG Games", "Program Files (x86)/Steam/steamapps/common",
                              "Program Files/Steam/steamapps/common", "XboxGames",
                              "Program Files", "Program Files (x86)"):
                    for name in GAME_DIR_NAMES:
                        add(drive_c / store / name, app, "porting-kit")
                        add(drive_c / store / name / "Content", app, "porting-kit")

    # Bare Wine prefixes with no .app around them.
    for root in _search_roots():
        for prefix in _listdir(root):
            drive_c = prefix / "drive_c"
            if not _is_dir(drive_c):
                continue
            for name in GAME_DIR_NAMES:
                add(drive_c / "GOG Games" / name, None, "wine-prefix")

    # A native/Steam Mac install, in case this ever runs somewhere else.
    for candidate in [
        HOME / "Library/Application Support/Steam/steamapps/common/Hollow Knight Silksong",
        Path("/Applications/Hollow Knight Silksong"),
    ]:
        add(candidate, None, "native")

    return found
