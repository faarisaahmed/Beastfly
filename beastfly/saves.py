"""Save-file snapshots.

Modded runs are the ones most likely to eat a save, and Silksong keeps its
saves inside the Wine prefix where nothing on the Mac side backs them up. So
Beastfly can snapshot them into ~/.beastfly/backups before each launch.
"""

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


def create(conf, label=""):
    """Zip the save folder. Returns (path, file_count) or raises OSError."""
    source = find_save_dir(conf)
    if source is None:
        raise OSError("Couldn't find Silksong's save folder for this install.")

    suffix = ("_" + _slug(label)) if label else ""
    target = backup_dir() / ("saves_%s%s.zip" % (time.strftime(STAMP), suffix))
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            # Player.log is regenerated every run and is the bulk of the folder.
            if path.suffix.lower() == ".log":
                continue
            zf.write(path, path.relative_to(source).as_posix())
            count += 1
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


def restore(conf, snapshot):
    """Replace the live saves with a snapshot, stashing the current ones first."""
    target = find_save_dir(conf)
    if target is None:
        raise OSError("Couldn't find Silksong's save folder for this install.")
    safety = create(conf, label="before-restore")
    with zipfile.ZipFile(snapshot) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
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
