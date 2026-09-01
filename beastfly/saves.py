"""Save-file snapshots.

Modded runs are the ones most likely to eat a save, and Silksong keeps its
saves inside the Wine prefix where nothing on the Mac side backs them up. So
Beastfly can snapshot them into ~/.beastfly/backups before each launch.
"""

import re
import shutil
import time
import zipfile
from pathlib import Path

from . import config as cfg

SAVE_FOLDER = "Team Cherry/Hollow Knight Silksong"
KEEP = 12                      # snapshots retained before the oldest is pruned
STAMP = "%Y-%m-%d_%H%M%S"


def find_save_dir(conf):
    """Where Silksong keeps its saves for this install, or None."""
    game = conf.game
    if game is None:
        return None

    # Windows build under Wine: <prefix>/drive_c/users/<user>/AppData/LocalLow/...
    for parent in game.parents:
        if parent.name == "drive_c":
            users = parent / "users"
            if not users.is_dir():
                break
            for user in _safe_iter(users):
                candidate = user / "AppData/LocalLow" / SAVE_FOLDER
                if candidate.is_dir():
                    return candidate
            break

    # Native macOS build.
    native = (Path.home() / "Library/Application Support"
              / "unity.Team Cherry.Hollow Knight Silksong")
    if native.is_dir():
        return native
    return None


def _safe_iter(path):
    try:
        return sorted(path.iterdir())
    except OSError:
        return []


def backup_dir():
    cfg.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return cfg.BACKUP_DIR


def snapshots():
    """Existing snapshots, newest first: [(path, when, size)]."""
    if not cfg.BACKUP_DIR.is_dir():
        return []
    out = []
    for path in cfg.BACKUP_DIR.glob("saves_*.zip"):
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append((path, stat.st_mtime, stat.st_size))
    out.sort(key=lambda row: -row[1])
    return out


# Silksong writes user1.dat .. user4.dat, each shadowed by a .bak1 and a
# version-stamped copy. Files are grouped by the digits after "user" so a slot
# travels with its backups.
_SLOT = re.compile(r"^user(\d*)(?:\.dat|_.*\.dat)(?:\.bak\d*)?$", re.I)
_PRIMARY = re.compile(r"^user\d*\.dat$", re.I)


def slots(conf):
    """Save slots and everything else. Returns ([slot], [other relative paths]).

    Each slot is {'label', 'files', 'size', 'mtime'} with files relative to the
    save folder.
    """
    source = find_save_dir(conf)
    if source is None:
        return [], []

    groups, other = {}, []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if path.suffix.lower() == ".log":
            continue
        match = _SLOT.match(path.name)
        if not match:
            other.append(relative)
            continue
        # "user.dat" and "user0_1.0.x.dat" are the same slot - identical bytes,
        # one just carries the version stamp. Treat a missing digit as 0.
        groups.setdefault(match.group(1) or "0", []).append(relative)

    result = []
    for key, files in groups.items():
        primary = next((f for f in files if _PRIMARY.match(f.name)), files[0])
        size = 0
        newest = 0.0
        for relative in files:
            try:
                stat = (source / relative).stat()
            except OSError:
                continue
            size += stat.st_size
            newest = max(newest, stat.st_mtime)
        result.append({"label": primary.name, "key": key, "files": files,
                       "size": size, "mtime": newest})
    # Newest first: the slot you're actually playing floats to the top.
    result.sort(key=lambda slot: -slot["mtime"])
    return result, other


def create(conf, label="", only=None):
    """Zip the save folder. Returns (path, file_count) or raises OSError."""
    source = find_save_dir(conf)
    if source is None:
        raise OSError("Couldn't find Silksong's save folder for this install.")

    suffix = ("_" + _slug(label)) if label else ""
    target = backup_dir() / ("saves_%s%s.zip" % (time.strftime(STAMP), suffix))
    wanted = None if only is None else {Path(p).as_posix() for p in only}

    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            # Player.log is regenerated every run and is the bulk of the folder.
            if path.suffix.lower() == ".log":
                continue
            relative = path.relative_to(source).as_posix()
            if wanted is not None and relative not in wanted:
                continue
            zf.write(path, relative)
            count += 1
    if not count:
        target.unlink(missing_ok=True)
        raise OSError("Nothing selected to back up.")
    prune()
    return target, count


def _slug(text):
    keep = [c if c.isalnum() or c in "-_" else "-" for c in str(text)]
    return "".join(keep).strip("-")[:40]


def prune(keep=KEEP):
    """Drop the oldest snapshots so backups can't grow without bound."""
    existing = snapshots()
    removed = []
    for path, _, _ in existing[keep:]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            pass
    return removed


def contents(snapshot):
    """Slot groupings inside a snapshot, same shape as slots()."""
    try:
        with zipfile.ZipFile(snapshot) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
    except (zipfile.BadZipFile, OSError):
        return [], []
    groups, other = {}, []
    for name in names:
        base = name.rsplit("/", 1)[-1]
        match = _SLOT.match(base)
        if not match:
            other.append(name)
            continue
        groups.setdefault(match.group(1) or "0", []).append(name)
    result = []
    for key, files in groups.items():
        primary = next((f for f in files
                        if _PRIMARY.match(f.rsplit("/", 1)[-1])), files[0])
        result.append({"label": primary.rsplit("/", 1)[-1], "key": key,
                       "files": files, "size": 0, "mtime": 0.0})
    result.sort(key=lambda slot: slot["label"])
    return result, other


def restore(conf, snapshot, only=None):
    """Replace the live saves with a snapshot, stashing the current ones first.

    Experimental. It puts the bytes back where they came from, which is all it
    claims to do - Silksong's own integrity checks, .bak1 shadow files and
    version-stamped copies are not something Beastfly understands.
    """
    target = find_save_dir(conf)
    if target is None:
        raise OSError("Couldn't find Silksong's save folder for this install.")
    safety = create(conf, label="before-restore")
    wanted = None if only is None else set(only)
    with zipfile.ZipFile(snapshot) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            if wanted is not None and name not in wanted:
                continue
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                continue
            destination = (target / relative).resolve()
            try:
                destination.relative_to(target.resolve())
            except ValueError:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(destination, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return safety[0]
