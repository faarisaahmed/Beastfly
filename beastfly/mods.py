"""Reading, installing, enabling and removing mods on disk.

The BepInEx tree is the single source of truth for *what is installed*; a
registry in ~/.beastfly/installed.json remembers *where it came from* so
updates and dependency checks work for mods added later.

A mod is enabled/disabled by renaming its assemblies (.dll <-> .dll.disabled)
rather than moving folders, so BepInEx configs and mod-local save data keep
their paths.
"""

import json
import shutil
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import config as cfg

# Areas of the BepInEx tree that can hold a mod. Order matters for display.
AREAS = ("plugins", "patchers", "monomod")
# core/ holds BepInEx's own assemblies, so it is never scanned for mods - but a
# mod that ships a folder there still needs to toggle and uninstall with the rest.
ATTACHED_AREAS = ("core",)
DISABLED_SUFFIXES = (".disabled", ".old")
LOADABLE = (".dll",)
REGISTRY_FILE = cfg.STATE_DIR / "installed.json"
SKIP_NAMES = {".DS_Store", "__MACOSX", "Thumbs.db"}


@dataclass
class Mod:
    id: str
    name: str = ""
    author: str = ""
    version: str = ""
    description: str = ""
    source: str = "manual"          # thunderstore | nexus | manual
    source_id: str = ""             # "Owner/Name" or a Nexus numeric id
    dependencies: list = field(default_factory=list)
    website: str = ""
    group: str = ""                 # parent folder, when the user files mods in categories
    enabled: bool = True
    roots: list = field(default_factory=list)   # absolute paths, as strings

    def __post_init__(self):
        if not self.name:
            self.name = self.id.split("/")[-1]

    @property
    def label(self):
        return self.id

    @property
    def paths(self):
        return [Path(r) for r in self.roots]

    def meta(self):
        """The subset worth persisting to the registry."""
        keep = ("id", "name", "author", "version", "description",
                "source", "source_id", "dependencies", "website")
        return {k: v for k, v in asdict(self).items() if k in keep}


# ---------------------------------------------------------------- registry

def load_registry():
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text())
        except (ValueError, OSError):
            pass
    return {}


def save_registry(registry):
    cfg.STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, indent=2, sort_keys=True))
    tmp.replace(REGISTRY_FILE)


def remember(mod):
    registry = load_registry()
    registry[mod.id] = mod.meta()
    save_registry(registry)


def forget(mod_id):
    registry = load_registry()
    if registry.pop(mod_id, None) is not None:
        save_registry(registry)


# ---------------------------------------------------------------- helpers

def _is_disabled_name(name):
    return any(name.endswith(s) for s in DISABLED_SUFFIXES)


def _base_name(name):
    for suffix in DISABLED_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _is_assembly(path):
    return _base_name(path.name).lower().endswith(LOADABLE)


def _assemblies(root):
    """Every .dll under root, enabled or not."""
    if root.is_file():
        return [root] if _is_assembly(root) else []
    out = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and _is_assembly(path):
            out.append(path)
    return out


def _has_direct_assembly(directory):
    try:
        return any(_is_assembly(p) for p in directory.iterdir() if p.is_file())
    except OSError:
        return False


def within(path, root):
    """True if `path` sits inside `root`. Every delete is gated on this.

    A mis-typed game path must never let a removal escape the BepInEx tree.
    """
    if root is None:
        return False
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False


def _read_manifest(directory):
    """Thunderstore manifest.json, if the mod shipped one."""
    manifest = directory / "manifest.json"
    if not manifest.exists():
        return {}
    try:
        # Thunderstore manifests are occasionally UTF-8 with a BOM.
        return json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        return {}


# ---------------------------------------------------------------- scanning

def _scan_directory(directory, area, prefix=""):
    """Yield (mod_id, root_path, group, manifest) for mods under `directory`.

    A directory is a mod when it carries a manifest or holds .dll files
    directly. Otherwise it is treated as a category folder and we descend,
    which is what lets a hand-made layout like plugins/QoL/MapMod work.
    """
    for entry in sorted(_safe_iter(directory)):
        if entry.name in SKIP_NAMES or entry.name.startswith("."):
            continue

        if entry.is_file():
            if _is_assembly(entry):
                # A loose .dll dropped straight into plugins/.
                mod_id = prefix + _base_name(entry.name)[: -len(".dll")]
                yield mod_id, entry, prefix.rstrip("/"), {}
            continue

        if not entry.is_dir():
            continue

        manifest = _read_manifest(entry)
        if manifest or _has_direct_assembly(entry):
            yield prefix + entry.name, entry, prefix.rstrip("/"), manifest
            continue

        # No assemblies here - descend and treat this level as a group.
        nested = list(_scan_directory(entry, area, prefix + entry.name + "/"))
        if nested:
            for item in nested:
                yield item
        elif area == "plugins":
            # An empty or asset-only folder: still surface it so it can be removed.
            yield prefix + entry.name, entry, prefix.rstrip("/"), {}


def _safe_iter(directory):
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def scan(conf):
    """Every installed mod, merged across BepInEx areas. Returns [Mod]."""
    registry = load_registry()
    bepinex = conf.bepinex
    if not bepinex or not bepinex.is_dir():
        return []

    merged = {}
    for area in AREAS:
        area_dir = bepinex / area
        if not area_dir.is_dir():
            continue
        for mod_id, root, group, manifest in _scan_directory(area_dir, area):
            mod = merged.get(mod_id)
            if mod is None:
                mod = Mod(id=mod_id, group=group)
                merged[mod_id] = mod
            mod.roots.append(str(root))
            _apply_manifest(mod, manifest)

    mods = []
    for mod in merged.values():
        for area in ATTACHED_AREAS:
            attached = bepinex / area / mod.id
            if attached.is_dir() and str(attached) not in mod.roots:
                mod.roots.append(str(attached))
        _apply_registry(mod, registry.get(mod.id, {}))
        _infer_source(mod)
        assemblies = [a for root in mod.paths for a in _assemblies(root)]
        active = [a for a in assemblies if not _is_disabled_name(a.name)]
        # No assemblies at all (asset-only folder): treat as enabled.
        mod.enabled = bool(active) or not assemblies
        mods.append(mod)

    mods.sort(key=lambda m: m.id.lower())
    return mods


def _apply_manifest(mod, manifest):
    if not manifest:
        return
    mod.name = manifest.get("name") or mod.name
    mod.version = manifest.get("version_number") or mod.version
    mod.description = manifest.get("description") or mod.description
    mod.website = manifest.get("website_url") or mod.website
    author = manifest.get("namespace") or manifest.get("author") or ""
    if author:
        mod.author = author
    deps = [d for d in manifest.get("dependencies") or [] if d and d.strip()]
    if deps:
        mod.dependencies = deps
    if author and manifest.get("name"):
        mod.source = "thunderstore"
        mod.source_id = "%s/%s" % (author, manifest["name"])


def _apply_registry(mod, entry):
    """Registry metadata wins over guesses, but never over a live manifest."""
    for key in ("author", "version", "description", "website", "source_id"):
        if entry.get(key) and not getattr(mod, key):
            setattr(mod, key, entry[key])
    if entry.get("dependencies") and not mod.dependencies:
        mod.dependencies = entry["dependencies"]
    if entry.get("source") and mod.source == "manual":
        mod.source = entry["source"]
    if entry.get("name") and mod.name == mod.id.split("/")[-1]:
        mod.name = entry["name"]


def _infer_source(mod):
    """Recognise Nexus download folder names, e.g. 'ToggleHUD-28-2-0-4-1758980847'."""
    if mod.source != "manual" or mod.source_id:
        return
    from .sources import nexus
    tail = mod.id.split("/")[-1]
    parsed = nexus.parse_folder_name(tail)
    if parsed:
        mod.source = "nexus"
        mod.source_id = str(parsed["mod_id"])
        # The folder name is a Nexus artefact; show the readable name instead.
        if mod.name == tail:
            mod.name = parsed["name"]
        mod.version = mod.version or parsed["version"]


def _norm(text):
    """Fold to comparable form: lowercase, letters and digits only.

    Folder names carry spaces, dashes, version numbers and Nexus timestamps, so
    "show damage", "ShowDamage" and "show-damage" all have to land together.
    """
    return "".join(c for c in str(text).lower() if c.isalnum())


def _subsequence(needle, haystack):
    """True if needle's chars appear in order ('sdh' -> 'showdamagehealthbar')."""
    position = 0
    for char in needle:
        position = haystack.find(char, position) + 1
        if position == 0:
            return False
    return True


def find(mods, query):
    """Match a user-typed name against installed mods, best first.

    Deliberately loose: nobody types a Nexus folder name like
    'ShowDamage HealthBar-28-2-0-4-1758980847', so anything that identifies the
    mod will do. Callers disambiguate with a picker when this returns several.
    """
    query = query.strip()
    lowered = query.lower()
    folded = _norm(query)
    if not folded:
        return []

    scored = []
    for mod in mods:
        aliases = {mod.id, mod.name, mod.id.split("/")[-1], mod.group, mod.author}
        if mod.source_id and "/" in mod.source_id:
            aliases.update(mod.source_id.split("/"))
        best = None
        for alias in aliases:
            if not alias:
                continue
            alias_folded = _norm(alias)
            if not alias_folded:
                continue
            if alias.lower() == lowered or alias_folded == folded:
                score = 0
            elif alias_folded.startswith(folded):
                score = 1
            elif folded in alias_folded:
                score = 2
            elif len(folded) >= 3 and _subsequence(folded, alias_folded):
                score = 3
            else:
                continue
            best = score if best is None else min(best, score)
        if best is not None:
            # Shorter ids win ties: the more specific match is usually meant.
            scored.append((best, len(mod.id), mod))

    scored.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in scored]


# ---------------------------------------------------------------- toggling

def set_enabled(mod, enabled, bepinex=None):
    """Rename the mod's assemblies. Returns the number of files touched."""
    touched = 0
    for root in mod.paths:
        if bepinex is not None and not within(root, bepinex):
            continue
        for assembly in _assemblies(root):
            currently_on = not _is_disabled_name(assembly.name)
            if currently_on == enabled:
                continue
            if enabled:
                target = assembly.with_name(_base_name(assembly.name))
            else:
                target = assembly.with_name(assembly.name + ".disabled")
            if target.exists():
                # Shouldn't happen, but never clobber a real file.
                continue
            try:
                assembly.rename(target)
                touched += 1
            except OSError:
                pass
    mod.enabled = enabled
    return touched


class UnsafePath(Exception):
    pass


def remove(mod, bepinex):
    """Delete every file this mod owns. Returns the paths removed.

    Refuses outright if any of the mod's paths resolve outside the BepInEx
    tree - that would mean the scan or the configured path is wrong, and
    deleting on a wrong guess is not recoverable.
    """
    if bepinex is None:
        raise UnsafePath("No BepInEx path configured; refusing to delete anything.")
    for root in mod.paths:
        if not within(root, bepinex):
            raise UnsafePath("%s is outside %s; refusing to delete it."
                             % (root, bepinex))

    removed = []
    for root in mod.paths:
        try:
            if root.is_dir():
                shutil.rmtree(root)
            elif root.exists():
                root.unlink()
            removed.append(root)
        except OSError:
            pass

    # Tidy up now-empty group folders (plugins/QoL/ once its last mod is gone).
    for root in mod.paths:
        parent = root.parent
        while (parent.name not in AREAS
               and within(parent, bepinex)
               and parent.is_dir() and not any(_safe_iter(parent))):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    forget(mod.id)
    return removed


# ---------------------------------------------------------------- installing

class InstallError(Exception):
    pass


def _safe_member(name, base):
    """Reject absolute paths and traversal before extracting."""
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    target = (base / relative).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target


def _zip_roots(names):
    return {Path(n).parts[0] for n in names if Path(n).parts}


def install_archive(archive, conf, mod_id=None, source="manual",
                    source_id="", version="", on_progress=None):
    """Extract a mod zip into the BepInEx tree, Thunderstore layout aware.

    Entries under plugins/, patchers/, monomod/ or core/ are routed to the
    matching BepInEx folder; anything else lands in plugins/<mod_id>/.
    """
    archive = Path(archive)
    bepinex = conf.bepinex
    if bepinex is None:
        raise InstallError("No game path configured. Run /setup first.")

    if archive.is_dir():
        return _install_folder(archive, conf, mod_id or archive.name)

    if archive.suffix.lower() == ".dll":
        mod_id = mod_id or archive.stem
        target = bepinex / "plugins" / mod_id
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive, target / archive.name)
        return _finish(Mod(id=mod_id, source=source, source_id=source_id,
                           version=version, roots=[str(target)]), conf)

    if archive.suffix.lower() != ".zip" or not zipfile.is_zipfile(archive):
        raise InstallError("%s is not a .zip or .dll. Unpack it manually, then /add the folder."
                           % archive.name)

    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        names = [n for n in names if Path(n).name not in SKIP_NAMES
                 and not n.startswith("__MACOSX")]
        if not names:
            raise InstallError("%s is empty." % archive.name)

        manifest = {}
        for name in names:
            if Path(name).name == "manifest.json":
                try:
                    manifest = json.loads(zf.read(name).decode("utf-8-sig"))
                except (ValueError, UnicodeDecodeError):
                    manifest = {}
                break

        if not mod_id:
            mod_id = _derive_id(manifest, archive)

        roots = _zip_roots(names)
        # A zip wrapped in one folder that isn't a BepInEx area: strip it.
        strip = ""
        if len(roots) == 1:
            only = next(iter(roots))
            if only.lower() not in ("plugins", "patchers", "monomod", "core"):
                strip = only + "/"

        written = set()
        total = len(names)
        try:
            _extract(zf, names, strip, bepinex, mod_id, written, total, on_progress)
        except Exception:
            # Never leave half a mod behind for BepInEx to choke on.
            for base in written:
                shutil.rmtree(base, ignore_errors=True)
            raise

    if not written:
        raise InstallError("Nothing installable found in %s." % archive.name)

    mod = Mod(id=mod_id, source=source, source_id=source_id,
              version=version, roots=sorted(written))
    _apply_manifest(mod, manifest)
    if source != "manual":
        mod.source, mod.source_id = source, source_id
    if version:
        mod.version = version
    return _finish(mod, conf)


def _extract(zf, names, strip, bepinex, mod_id, written, total, on_progress):
    for index, name in enumerate(names, 1):
            relative = name[len(strip):] if strip and name.startswith(strip) else name
            if not relative:
                continue
            parts = Path(relative).parts
            area = parts[0].lower() if parts else ""
            if area in ("plugins", "patchers", "monomod", "core") and len(parts) > 1:
                base = bepinex / area / mod_id
                inner = Path(*parts[1:])
            else:
                base = bepinex / "plugins" / mod_id
                inner = Path(relative)

            target = _safe_member(str(inner), base)
            if target is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written.add(str(base))
            if on_progress:
                on_progress(index, total)


def _install_folder(folder, conf, mod_id):
    target = conf.bepinex / "plugins" / mod_id
    if target.exists():
        if not within(target, conf.bepinex):
            raise InstallError("Refusing to overwrite %s." % target)
        shutil.rmtree(target)
    shutil.copytree(folder, target, ignore=shutil.ignore_patterns(*SKIP_NAMES))
    mod = Mod(id=mod_id, roots=[str(target)])
    _apply_manifest(mod, _read_manifest(target))
    return _finish(mod, conf)


def _derive_id(manifest, archive):
    """Thunderstore full name if we have one, else a cleaned-up file name."""
    if manifest.get("name"):
        namespace = manifest.get("namespace") or manifest.get("author")
        if namespace:
            return "%s-%s" % (namespace, manifest["name"])
        return manifest["name"]
    stem = archive.stem
    from .sources import nexus
    parsed = nexus.parse_folder_name(stem)
    if parsed:
        return parsed["name"].strip().replace(" ", "")
    return stem


def _finish(mod, conf):
    remember(mod)
    return mod


# ---------------------------------------------------------------- BepInEx

BEPINEX_ROOT_FILES = ("winhttp.dll", "doorstop_config.ini", "run_bepinex.sh",
                      ".doorstop_version", "changelog.txt", "doorstop_libs")


def find_bepinex_package(conf):
    """The BepInEx pack for this community, from Thunderstore."""
    from .sources import thunderstore
    best = None
    for package in thunderstore.fetch(conf):
        name = (package.get("name") or "").lower()
        owner = (package.get("owner") or "").lower()
        if "bepinexpack" in name.replace("_", "") and owner == "bepinex":
            return package
        if "bepinex" in name and best is None:
            best = package
    return best


def install_bepinex(archive, conf, on_progress=None):
    """Unpack a BepInEx pack into the game root.

    These zips wrap everything in a folder like 'BepInExPack/' and expect
    their contents (BepInEx/, winhttp.dll, doorstop_config.ini) to sit
    alongside the game exe, so they can't go through install_archive.
    """
    game = conf.game
    if game is None:
        raise InstallError("No game path configured.")
    if not zipfile.is_zipfile(archive):
        raise InstallError("%s is not a zip." % Path(archive).name)

    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist()
                 if not n.endswith("/") and not n.startswith("__MACOSX")
                 and Path(n).name not in SKIP_NAMES]
        roots = _zip_roots(names)
        # Strip a single wrapper folder, but never strip 'BepInEx' itself.
        strip = ""
        if len(roots) == 1:
            only = next(iter(roots))
            if only.lower() != "bepinex":
                strip = only + "/"

        total = len(names)
        written = 0
        for index, name in enumerate(names, 1):
            relative = name[len(strip):] if strip and name.startswith(strip) else name
            if not relative:
                continue
            target = _safe_member(relative, game)
            if target is None:
                continue
            # Never overwrite an existing config the user has tuned.
            if target.exists() and target.suffix in (".cfg", ".ini") and written:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written += 1
            if on_progress:
                on_progress(index, total)

    for area in AREAS:
        (conf.bepinex / area).mkdir(parents=True, exist_ok=True)
    return written


# ---------------------------------------------------- recognising downloads

# Inspecting a zip means reading its central directory, so results are cached
# against (path, mtime, size) - a Downloads folder can hold hundreds of files.
_probe_cache = {}

# macOS bundles are directories full of assemblies but are never mods - a Wine
# wrapper like Silksong.app holds dozens of .dll files.
BUNDLE_SUFFIXES = (".app", ".framework", ".bundle", ".band", ".plugin",
                   ".kext", ".pkg", ".dsym", ".xcodeproj", ".photoslibrary")


def describe_archive(path):
    """What kind of mod content `path` holds, or None if it isn't a mod.

    Returns a short description ("3 dlls", "manifest + 1 dll", "folder, 2 dlls")
    suitable for showing next to the file name.
    """
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime, stat.st_size)
    if key in _probe_cache:
        return _probe_cache[key]
    result = _describe(path)
    _probe_cache[key] = result
    return result


def _summary(dlls, manifest, prefix=""):
    if not dlls and not manifest:
        return None
    parts = []
    if manifest:
        parts.append("manifest")
    if dlls:
        parts.append("%d dll%s" % (dlls, "" if dlls == 1 else "s"))
    return prefix + " + ".join(parts)


def _describe(path):
    name = path.name
    if name in SKIP_NAMES or name.startswith("."):
        return None

    if path.is_file():
        if name.lower().endswith(".dll"):
            return "1 dll"
        if not name.lower().endswith(".zip"):
            return None
        if not zipfile.is_zipfile(path):
            return None
        try:
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
        except (zipfile.BadZipFile, OSError):
            return None
        dlls = manifest = 0
        for entry in names:
            if entry.startswith("__MACOSX"):
                continue
            base = entry.rsplit("/", 1)[-1].lower()
            if base.endswith(".dll"):
                dlls += 1
            elif base == "manifest.json":
                manifest = 1
        return _summary(dlls, manifest)

    if path.is_dir():
        if path.suffix.lower() in BUNDLE_SUFFIXES:
            return None
        dlls = manifest = 0
        try:
            for entry in path.rglob("*"):
                if not entry.is_file():
                    continue
                base = entry.name.lower()
                if base.endswith(".dll"):
                    dlls += 1
                elif base == "manifest.json":
                    manifest = 1
                if dlls > 40:
                    break
        except OSError:
            return None
        return _summary(dlls, manifest, prefix="folder, ")

    return None
