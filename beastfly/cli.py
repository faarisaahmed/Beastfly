"""The Beastfly command loop: dispatch, rendering, and every command."""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config as cfg
from . import deps as deps_mod
from . import game as game_mod
from . import mods as mods_mod
from . import picker
from . import prompt as prompt_mod
from . import saves as saves_mod
from . import ui
from .config import Config, find_installs
from .profiles import Profiles, ProfileError
from .sources import nexus, thunderstore

PROMPT = "beastfly> "


class App:
    def __init__(self):
        self.conf = Config()
        self.profiles = Profiles()
        self._mods = None
        self.running = True

    # ------------------------------------------------------------ state

    def mods(self, refresh=False):
        if self._mods is None or refresh:
            self._mods = mods_mod.scan(self.conf)
        return self._mods

    def invalidate(self):
        self._mods = None

    def require_game(self):
        if not self.conf.configured:
            ui.fail("No game path configured yet. Run " + ui.accent("/setup") + ".")
            return False
        if not self.conf.bepinex_installed:
            ui.note("BepInEx isn't installed in %s." % self.conf.game)
            ui.info("Run /setup to install it.")
        return True

    def pick_mod(self, query, action="use"):
        """Resolve a user-typed name to one installed mod, asking if ambiguous."""
        matches = mods_mod.find(self.mods(), query)
        if not matches:
            ui.fail("No installed mod matching " + ui.bold(query) + ".")
            near = [m.id for m in self.mods()][:0]
            if near:
                ui.info("Did you mean: " + ", ".join(near))
            return None
        if len(matches) == 1:
            return matches[0]
        return ui.choose(
            "Which mod to %s?" % action,
            matches[:9],
            lambda m: "%s %s" % (ui.state(m.enabled), m.id),
        )

    # ------------------------------------------------------------ dispatch

    def dispatch(self, line):
        line = line.strip()
        if not line:
            return
        if line.startswith("/"):
            line = line[1:]
        parts = line.split()
        name, args = parts[0].lower(), parts[1:]

        handler = COMMANDS.get(name)
        if handler is None:
            suggestions = [c for c in COMMANDS if c.startswith(name)]
            ui.fail("Unknown command " + ui.bold("/" + name) + ".")
            if suggestions:
                ui.info("Did you mean: " + ", ".join("/" + s for s in sorted(suggestions)))
            else:
                ui.info("/help lists everything.")
            return
        try:
            handler[0](self, args)
        except (ProfileError, mods_mod.InstallError, mods_mod.UnsafePath,
                game_mod.LaunchError, thunderstore.SourceError,
                nexus.NexusError) as error:
            ui.fail(str(error))
        except KeyboardInterrupt:
            print()
            ui.info("Cancelled.")
        except Exception as error:                    # noqa: BLE001 - see below
            # A bug in one command must not take down the session. Show enough
            # to report it, then carry on.
            print()
            ui.fail("%s: %s" % (type(error).__name__, error))
            ui.info("That's a bug in Beastfly, not your setup.")
            ui.info("Details: BEASTFLY_DEBUG=1 beastfly %s" % name)
            if os.environ.get("BEASTFLY_DEBUG"):
                import traceback
                traceback.print_exc()

    def repl(self):
        print()
        print(ui.title())
        self.startup_report()
        entries = menu_entries()
        provider = arg_provider(self)
        history = []
        interrupts = 0
        while self.running:
            try:
                line = prompt_mod.read_line(ui.accent(PROMPT), entries, history,
                                            provider)
            except EOFError:
                print()
                cmd_exit(self, [])
                break
            except KeyboardInterrupt:
                print()
                interrupts += 1
                if interrupts >= 2:
                    cmd_exit(self, [])
                    break
                ui.info("Press Ctrl-C again to exit, or /exit.")
                continue
            interrupts = 0
            if line.strip() and (not history or history[-1] != line.strip()):
                history.append(line.strip())
            self.dispatch(line)

    def startup_report(self):
        if not self.conf.configured:
            print()
            ui.note("First run - no game found yet. Type " + ui.accent("/setup") + " to begin.")
            print()
            return
        installed = self.mods()
        enabled = sum(1 for m in installed if m.enabled)
        drifted = ui.warn("*") if self.profiles.modified(installed) else ""
        ui.info("%s%s  ·  %s, %d enabled  ·  %s" % (
            ui.bold(self.profiles.active), drifted,
            ui.plural(len(installed), "mod"),
            enabled,
            "BepInEx ok" if self.conf.bepinex_installed else "BepInEx missing",
        ))
        if self.conf["show_update_notifications"] and self.conf["check_updates"]:
            pending = self.cached_update_count()
            if pending:
                ui.note("%s available. Run /updates." % ui.plural(pending, "update"))
        print()

    def cached_update_count(self):
        """Update count from the cached index only - never blocks startup."""
        cache = cfg.CACHE_DIR / ("thunderstore-%s.json" % self.conf["thunderstore_community"])
        if not cache.exists():
            return 0
        try:
            index = thunderstore.index(self.conf)
        except thunderstore.SourceError:
            return 0
        count = 0
        for mod in self.mods():
            if mod.source != "thunderstore" or not mod.source_id or not mod.version:
                continue
            package = index.get(mod.source_id.replace("/", "-").lower())
            if package and thunderstore.version_of(package) != mod.version:
                count += 1
        return count


# ==================================================================== MODS

def cmd_ls(app, args):
    if not app.require_game():
        return
    installed = app.mods(refresh=True)
    if not installed:
        print()
        ui.info("No mods installed. Use /add <mod> or /search <query>.")
        print()
        return

    show_disabled_only = "--disabled" in args
    show_enabled_only = "--enabled" in args
    listing = [m for m in installed
               if not (show_disabled_only and m.enabled)
               and not (show_enabled_only and not m.enabled)]

    enabled = sum(1 for m in installed if m.enabled)
    print()
    print(ui.header("Installed mods  " + ui.grey("· " + app.profiles.active)))
    print()

    group = object()
    for mod in listing:
        if mod.group != group:
            group = mod.group
            if group:
                print("  " + ui.grey(group + "/"))
        indent = "    " if mod.group else "  "
        name = mod.name if mod.group else (mod.name or mod.id)
        left = "%s%s %s" % (indent, ui.state(mod.enabled),
                            ui.white(ui.truncate(name, 28)))
        right = ui.pad(ui.truncate(mod.version or "", 9), 10) + mod.source
        print(ui.pad(left, 34) + ui.grey(right))

    print()
    ui.info("%s, %d enabled, %d disabled" % (
        ui.plural(len(installed), "mod"), enabled, len(installed) - enabled))
    print()


def cmd_toggle(app, args):
    """Turn mods on and off. A name flips that mod; no name opens the list."""
    if not app.require_game():
        return
    if args:
        mod = app.pick_mod(" ".join(args), "toggle")
        if mod is None:
            return
        return _toggle(app, [mod.id], not mod.enabled)

    installed = app.mods(refresh=True)
    if not installed:
        ui.info("No mods installed. Use /add to install some.")
        return
    if not picker.available():
        return cmd_ls(app, [])

    labels = _label_for(installed)
    rows = [picker.Row(labels[m.id],
                       " ".join(x for x in (m.version, m.source) if x),
                       checked=m.enabled, payload=m)
            for m in installed]
    header = (ui.bold(ui.white(app.profiles.active)) + ui.grey("  ·  ")
              + ui.grey("%s installed" % ui.plural(len(installed), "mod")))

    result = picker.checklist(header, rows)
    if result is None:
        ui.info("No changes.")
        return
    _note_if_running(app)

    changed = []
    for row in result:
        mod = row.payload
        if row.checked != mod.enabled:
            if mods_mod.set_enabled(mod, row.checked, app.conf.bepinex):
                changed.append((mod, row.checked))

    if not changed:
        ui.info("No changes.")
        return
    for mod, enabled in changed:
        print("  " + ui.state(enabled) + " " + (mod.name or mod.id))
    ui.good("%s updated." % ui.plural(len(changed), "mod"))

    app.invalidate()
    if app.conf["remember_profile"]:
        app.profiles.store(app.profiles.active, app.mods(refresh=True))
        ui.info("Saved to profile %s." % app.profiles.active)
    else:
        _drift_hint(app)


def cmd_info(app, args):
    if not args:
        return usage("/info <mod>")
    if not app.require_game():
        return
    mod = app.pick_mod(" ".join(args), "inspect")
    if mod is None:
        return

    print()
    print(ui.header(mod.name or mod.id))
    print()
    rows = [
        ("Id", mod.id),
        ("Version", mod.version or ui.grey("unknown")),
        ("Author", mod.author or ui.grey("unknown")),
        ("Source", {"thunderstore": "Thunderstore", "nexus": "Nexus Mods"}.get(
            mod.source, "Manual install")),
        ("Status", ui.ok("enabled") if mod.enabled else ui.bad("disabled")),
    ]
    if mod.source == "nexus" and mod.source_id:
        rows.append(("Nexus page", nexus.page_url(app.conf, mod.source_id)))
    elif mod.website:
        rows.append(("Website", mod.website))
    for label, value in rows:
        print(ui.field(label, value, 14))

    if mod.description:
        print()
        print(ui.field("About", "", 14).rstrip())
        for line in _wrap(mod.description, ui.width() - 20):
            print("      " + ui.grey(line))

    print()
    print("  " + ui.white("Files"))
    for root in mod.paths:
        try:
            shown = root.relative_to(app.conf.bepinex)
        except ValueError:
            shown = root
        print("      " + ui.grey("BepInEx/" + str(shown)))

    if app.conf["show_deps"]:
        print()
        print("  " + ui.white("Dependencies"))
        tree = deps_mod.tree(mod, app.mods(), app.conf)
        if not tree["children"]:
            print("      " + ui.grey("none declared"))
        else:
            _print_branches(tree["children"], "      ")
        gaps = deps_mod.missing(mod, app.mods(), app.conf)
        if gaps:
            print()
            ui.note("%s not installed:" % ui.plural(len(gaps), "dependency", "dependencies"))
            _report_missing(app, [
                {"dependency": g, "key": thunderstore.split_dependency(g)[0],
                 "wanted": thunderstore.split_dependency(g)[1],
                 "package": deps_mod.available(g, app.conf)} for g in gaps])
            ui.info("/missing installs the ones on Thunderstore.")
    print()


def _print_branches(children, prefix):
    for index, node in enumerate(children):
        last = index == len(children) - 1
        elbow = "└── " if last else "├── "
        note = ui.grey("  " + node["note"]) if node["note"] else ""
        mark = ui.ok(ui.ON) if node["ok"] else ui.bad(ui.OFF)
        print(ui.grey(prefix + elbow) + node["label"] + " " + mark + note)
        if node["children"]:
            _print_branches(node["children"], prefix + ("    " if last else "│   "))


def cmd_enable(app, args):
    _toggle(app, args, True)


def cmd_disable(app, args):
    _toggle(app, args, False)


def _toggle(app, args, enabled):
    verb = "enable" if enabled else "disable"
    if not args:
        # Nothing named: the checklist is a better answer than a usage line.
        if picker.available():
            return cmd_toggle(app, [])
        return usage("/%s <mod>" % verb)
    if not app.require_game():
        return

    if args[0] in ("--all", "all"):
        targets = [m for m in app.mods() if m.enabled != enabled]
        if not targets:
            ui.info("Nothing to %s." % verb)
            return
        if not ui.confirm("%s %s?" % (verb.capitalize(), ui.plural(len(targets), "mod")), True):
            return
        for mod in targets:
            mods_mod.set_enabled(mod, enabled, app.conf.bepinex)
        ui.good("%sd %s." % (verb.capitalize(), ui.plural(len(targets), "mod")))
        app.invalidate()
        _drift_hint(app)
        return

    mod = app.pick_mod(" ".join(args), verb)
    if mod is None:
        return
    if mod.enabled == enabled:
        ui.info("%s is already %sd." % (mod.id, verb))
        return

    _note_if_running(app)
    touched = mods_mod.set_enabled(mod, enabled, app.conf.bepinex)
    if not touched:
        ui.fail("Couldn't rename any assemblies for %s. Is the game running?" % mod.id)
        return
    ui.good("%s %s (%s)." % (mod.id, verb + "d", ui.plural(touched, "file")))

    if enabled:
        gaps = deps_mod.missing(mod, app.mods(), app.conf)
        if gaps:
            ui.note("%s missing - %s may not load:"
                    % (ui.plural(len(gaps), "dependency", "dependencies"), mod.name or mod.id))
            _report_missing(app, [
                {"dependency": g, "key": thunderstore.split_dependency(g)[0],
                 "wanted": thunderstore.split_dependency(g)[1],
                 "package": deps_mod.available(g, app.conf)} for g in gaps])
    _drift_hint(app)


def cmd_remove(app, args):
    if not args:
        return usage("/remove <mod>")
    if not app.require_game():
        return
    mod = app.pick_mod(" ".join(args), "remove")
    if mod is None:
        return

    dependents = _dependents(app, mod)
    if dependents:
        ui.note("%s is required by: %s" % (mod.id, ", ".join(d.id for d in dependents)))

    if app.conf["confirm_remove"]:
        print()
        for root in mod.paths:
            print("  " + ui.grey("delete " + str(root)))
        print()
        if not ui.confirm("Remove %s?" % ui.bold(mod.id), False):
            ui.info("Kept.")
            return

    _note_if_running(app)
    removed = mods_mod.remove(mod, app.conf.bepinex)
    app.profiles.drop_mod(mod.id)
    app.invalidate()
    ui.good("Removed %s (%s)." % (mod.id, ui.plural(len(removed), "path")))


def _report_missing(app, gaps, indent="      "):
    """Print each unmet dependency with somewhere to get it."""
    for gap in gaps:
        wanted = ui.grey("  wants " + gap["wanted"]) if gap.get("wanted") else ""
        where = (ui.grey("  on Thunderstore") if gap.get("package")
                 else ui.grey("  not on Thunderstore"))
        print(indent + ui.bad(ui.OFF) + " " + ui.white(gap["key"]) + wanted + where)
        for label, url in deps_mod.links(gap["dependency"], app.conf, gap.get("package")):
            print(indent + "    " + ui.grey(label + ": ") + url)


_running_warned = []


def _note_if_running(app):
    """Say so once per session: a running game won't pick up changes."""
    if _running_warned:
        return
    if game_mod.is_running():
        _running_warned.append(True)
        ui.note("Silksong is running - changes take effect next launch.")


def _drift_hint(app):
    """Nudge towards /profiles save once the live set leaves the saved snapshot."""
    if not app.profiles.modified(app.mods(refresh=True)):
        return
    ui.info("Unsaved changes to profile %s - /profiles save to keep them."
            % app.profiles.active)


def _dependents(app, mod):
    """Installed mods that declare `mod` as a dependency."""
    keys = {mod.id.lower(), (mod.name or "").lower()}
    if mod.source_id:
        keys.add(mod.source_id.replace("/", "-").lower())
    out = []
    for other in app.mods():
        if other.id == mod.id:
            continue
        for dependency in deps_mod.dependencies_of(other, app.conf):
            key, _ = thunderstore.split_dependency(dependency)
            if key.lower() in keys:
                out.append(other)
                break
    return out


def cmd_search(app, args):
    if not args:
        return usage("/search <query>")
    query = " ".join(args)
    ui.info("Searching Thunderstore...")
    results = thunderstore.search(app.conf, query, limit=15)
    ui.progress_done()
    if not results:
        ui.fail("Nothing on Thunderstore matches " + ui.bold(query) + ".")
        return

    installed = {m.source_id.replace("/", "-").lower()
                 for m in app.mods() if m.source_id}
    print()
    print(ui.header("Thunderstore  " + ui.grey("· " + query)))
    print()
    for package in results:
        name = thunderstore.full_name(package)
        version = thunderstore.latest(package) or {}
        mark = ui.ok(ui.ON) if name.lower() in installed else " "
        print("  %s %s %s" % (mark, ui.white(ui.truncate(package.get("name", ""), 26)).ljust(26),
                              ui.grey("%-9s %s" % (
                                  ui.truncate(version.get("version_number", ""), 8),
                                  ui.truncate(version.get("description", ""), max(10, ui.width() - 48))))))
    print()
    ui.info("%s found. Install with /add <name>." % ui.plural(len(results), "result"))
    print()


def cmd_add(app, args):
    if not app.require_game():
        return
    words = [a for a in args if not a.startswith("--")]

    if not words:
        return _add_from_downloads(app, preselect=False)
    if words[0].lower() == "all":
        return _add_from_downloads(app, preselect=True)

    query = " ".join(words)
    prefer_local = "--local" in args
    prefer_remote = "--thunderstore" in args or "--remote" in args

    candidates = []
    if not prefer_remote:
        candidates += [("local", path) for path in _local_candidates(app, query)]
    if not prefer_local:
        try:
            for package in thunderstore.search(app.conf, query, limit=6):
                candidates.append(("thunderstore", package))
        except thunderstore.SourceError as error:
            if not candidates:
                raise
            ui.note(str(error))

    if not candidates:
        ui.fail("Nothing matching " + ui.bold(query) + ".")
        ui.info("Looked in %s and on Thunderstore." % app.conf.downloads)
        return

    def render(item):
        kind, value = item
        if kind == "local":
            size = _human_size(value)
            return "%s %s" % (ui.white(ui.truncate(value.name, 40)),
                              ui.grey("Downloads" + (" · " + size if size else "")))
        return "%s %s" % (ui.white(ui.truncate(thunderstore.full_name(value), 40)),
                          ui.grey("Thunderstore · " + thunderstore.version_of(value)))

    chosen = ui.choose("Install which?", candidates[:9], render)
    if chosen is None:
        ui.info("Cancelled.")
        return

    kind, value = chosen
    if kind == "local":
        _install_local(app, value)
    else:
        _install_package(app, value)
    app.invalidate()


def _add_from_downloads(app, preselect):
    """Install several mods from the Downloads folder in one pass."""
    found = _installable_downloads(app)
    if not found:
        ui.fail("Nothing installable in %s." % app.conf.downloads)
        ui.info("Beastfly looks for .zip files, loose .dll files and mod folders.")
        return

    known = {m.id.split("/")[-1].lower() for m in app.mods()}
    rows = []
    for path, description in found:
        meta = description
        size = _human_size(path)
        if size:
            meta += "  " + size
        rows.append(picker.Row(path.name, meta,
                               checked=preselect or path.stem.lower() not in known,
                               payload=path))

    if preselect:
        # /add all is the no-interaction path: just confirm the whole list.
        chosen = [row.payload for row in rows]
        print()
        for path in chosen:
            print("  " + ui.grey(path.name))
        print()
        if not ui.confirm("Install %s into profile %s?"
                          % (ui.plural(len(chosen), "item"), app.profiles.active), True):
            return
    elif picker.available():
        header = (ui.bold(ui.white("Install from Downloads")) + ui.grey("  ·  ")
                  + ui.grey("into profile " + app.profiles.active))
        result = picker.checklist(header, rows)
        if result is None:
            ui.info("Nothing installed.")
            return
        chosen = [row.payload for row in result if row.checked]
    else:
        ui.info("Interactive mode needs a terminal; use /add all or /add <name>.")
        return

    if not chosen:
        ui.info("Nothing selected.")
        return

    installed_count = 0
    for path in chosen:
        try:
            _install_local(app, path)
            installed_count += 1
        except (mods_mod.InstallError, OSError) as error:
            ui.fail("%s: %s" % (path.name, error))
    app.invalidate()
    print()
    ui.good("Installed %s into profile %s."
            % (ui.plural(installed_count, "mod"), app.profiles.active))


def _local_candidates(app, query):
    """Installable things in the Downloads folder matching the query."""
    downloads = app.conf.downloads
    if not downloads.is_dir():
        return []
    lowered = query.lower()
    hits = []
    try:
        entries = list(downloads.iterdir())
    except OSError:
        return []
    for entry in entries:
        if mods_mod._norm(lowered) not in mods_mod._norm(entry.name):
            continue
        if mods_mod.describe_archive(entry) is None:
            continue
        hits.append(entry)
    # Newest first: the thing you just downloaded is usually the thing you want.
    hits.sort(key=lambda p: -p.stat().st_mtime)
    return hits[:9]


def _install_local(app, path):
    label = ui.truncate(path.name, 22)
    mod = mods_mod.install_archive(
        path, app.conf,
        on_progress=lambda done, total: ui.progress(label, done, total))
    ui.progress_done()
    _post_install(app, mod, resolve_deps=True)


def _install_package(app, package, version=None, quiet=False):
    name = thunderstore.full_name(package)
    version_data = version or thunderstore.latest(package)
    if version_data is None:
        raise thunderstore.SourceError("%s has no published versions." % name)
    number = version_data.get("version_number", "")

    with tempfile.TemporaryDirectory(prefix="beastfly-") as scratch:
        archive = Path(scratch) / ("%s-%s.zip" % (name, number))
        label = ui.truncate(name, 22)
        thunderstore.download(package, archive, version_data,
                              on_progress=lambda d, t: ui.progress(label, d, t))
        ui.progress_done()
        mod = mods_mod.install_archive(
            archive, app.conf, mod_id=name, source="thunderstore",
            source_id="%s/%s" % (package.get("owner", ""), package.get("name", "")),
            version=number)
    if not quiet:
        _post_install(app, mod, resolve_deps=True, package=package, version=version_data)
    return mod


def _post_install(app, mod, resolve_deps=False, package=None, version=None):
    ui.good("Installed %s%s." % (mod.id, " " + mod.version if mod.version else ""))
    app.invalidate()

    enabled = app.conf["auto_enable_new"]
    if not enabled:
        mods_mod.set_enabled(mod, False, app.conf.bepinex)
        ui.info("Left disabled (auto-enable is off).")
    # New mods belong to the profile that installed them, not to every profile.
    app.profiles.scope_to_active(mod.id, enabled)

    if not resolve_deps:
        return
    declared = thunderstore.dependencies(package, version) if package \
        else deps_mod.dependencies_of(mod, app.conf)
    pending = []
    index = deps_mod.installed_index(app.mods(refresh=True))
    for dependency in declared:
        if deps_mod.is_bepinex(dependency):
            if not app.conf.bepinex_installed:
                ui.note("This mod needs BepInEx. Run /setup to install it.")
            continue
        resolved, key, _ = deps_mod.resolve(dependency, index)
        if resolved is None:
            pending.append(dependency)

    if not pending:
        return

    gaps = []
    for dependency in pending:
        key, wanted = thunderstore.split_dependency(dependency)
        gaps.append({"dependency": dependency, "key": key, "wanted": wanted,
                     "package": deps_mod.available(dependency, app.conf)})

    if not app.conf["auto_install_deps"]:
        ui.note("%s missing (auto-install is off):"
                % ui.plural(len(gaps), "dependency", "dependencies"))
        _report_missing(app, gaps)
        return

    for gap in [g for g in gaps if g["package"]]:
        ui.info("Installing dependency " + gap["key"] + "...")
        try:
            dependency_mod = _install_package(app, gap["package"], quiet=True)
            ui.good("Installed %s %s." % (dependency_mod.id, dependency_mod.version))
            app.invalidate()
        except (thunderstore.SourceError, mods_mod.InstallError) as error:
            ui.fail("Dependency %s failed: %s" % (gap["key"], error))

    unavailable = [g for g in gaps if not g["package"]]
    if unavailable:
        ui.note("%s not on Thunderstore - download by hand:"
                % ui.plural(len(unavailable), "dependency", "dependencies"))
        _report_missing(app, unavailable)


def cmd_missing(app, args):
    if not app.require_game():
        return
    installed = app.mods(refresh=True)
    report = deps_mod.audit(installed, app.conf)

    print()
    print(ui.header("Missing dependencies"))
    print()
    if not report:
        ui.good("Every installed mod has what it needs.")
        print()
        return

    installable, needs_bepinex = {}, False
    for mod, gaps in report:
        status = "enabled" if mod.enabled else "disabled"
        print("  " + ui.white(mod.name or mod.id) + ui.grey("  " + status))
        _report_missing(app, gaps)
        print()
        for gap in gaps:
            if gap["key"] == "BepInEx":
                needs_bepinex = True
            elif gap["package"]:
                installable[thunderstore.full_name(gap["package"])] = gap["package"]

    ui.info("%s with unmet dependencies." % ui.plural(len(report), "mod"))
    if needs_bepinex:
        ui.note("BepInEx itself is missing - run /setup to install it.")
    if not installable:
        ui.info("None of the gaps are on Thunderstore; use the links above.")
        print()
        return

    print()
    if not ui.confirm("Install %s from Thunderstore?"
                      % ui.plural(len(installable), "dependency", "dependencies"), True):
        print()
        return

    for package in installable.values():
        try:
            fresh = _install_package(app, package, quiet=True)
            ui.good("Installed %s %s." % (fresh.id, fresh.version or ""))
            app.invalidate()
        except (thunderstore.SourceError, mods_mod.InstallError) as error:
            ui.fail("%s: %s" % (thunderstore.full_name(package), error))

    remaining = deps_mod.audit(app.mods(refresh=True), app.conf)
    print()
    if remaining:
        ui.note("%s still has gaps - run /missing again."
                % ui.plural(len(remaining), "mod"))
    else:
        ui.good("All dependencies satisfied.")
    print()


def _apply_update(app, mod, package, current, latest):
    was_enabled = mod.enabled
    ui.info("%s -> %s" % (current or "unknown", latest))
    mods_mod.remove(mod, app.conf.bepinex)
    fresh = _install_package(app, package, quiet=True)
    if not was_enabled:
        mods_mod.set_enabled(fresh, False, app.conf.bepinex)
    app.invalidate()
    ui.good("Updated %s to %s." % (fresh.id, fresh.version or latest))


def _report_nexus(app, mod, current, latest):
    ui.note("%s: %s -> %s available on Nexus." % (mod.id, current or "?", latest))
    ui.info("Nexus blocks API downloads, so grab it here, then /add it:")
    ui.info("  " + nexus.page_url(app.conf, mod.source_id))


def _check_one(app, mod):
    """Returns (current, latest, package) or None if not checkable."""
    if mod.source == "thunderstore" and mod.source_id:
        package = thunderstore.by_full_name(app.conf, mod.source_id.replace("/", "-"))
        if package is None:
            return mod.version, "", None
        return mod.version, thunderstore.version_of(package), package
    if mod.source == "nexus" and mod.source_id:
        if not nexus.configured(app.conf):
            return None
        return mod.version, nexus.latest_version(app.conf, mod.source_id), None
    return None


def cmd_updates(app, args):
    if not app.require_game():
        return
    installed = app.mods(refresh=True)
    sourced = [m for m in installed if m.source in ("thunderstore", "nexus") and m.source_id]
    # Nexus needs a key; without one those mods can be listed but not checked.
    blocked = [m for m in sourced if m.source == "nexus" and not nexus.configured(app.conf)]
    checkable = [m for m in sourced if m not in blocked]
    manual = [m for m in installed if m not in sourced]

    print()
    print(ui.header("Updates"))
    print()
    if not checkable:
        ui.info("No mods Beastfly can version-check right now.")
        _manual_hint(app, manual, blocked)
        return

    ui.info("Checking %s..." % ui.plural(len(checkable), "mod"))
    outdated, errors = [], []
    for mod in checkable:
        try:
            result = _check_one(app, mod)
        except nexus.NexusError as error:
            errors.append((mod, str(error)))
            continue
        if result is None:
            continue
        current, latest, package = result
        if latest and current and latest != current:
            outdated.append((mod, current, latest, package))
    ui.progress_done()
    print()

    if not outdated:
        ui.good("Everything is up to date.")
    for mod, current, latest, _ in outdated:
        print("  " + ui.warn(ui.UPDATE) + " "
              + ui.pad(ui.white(ui.truncate(mod.id, 28)), 30)
              + ui.grey("%s -> " % current) + ui.warn(latest)
              + ui.grey("  " + mod.source))
    for mod, message in errors:
        print("  " + ui.bad(ui.OFF) + " "
              + ui.pad(ui.truncate(mod.id, 28), 30) + ui.grey(message))

    print()
    _manual_hint(app, manual, blocked)
    if not outdated:
        print()
        return

    thunderstore_updates = [row for row in outdated if row[0].source == "thunderstore"]
    nexus_updates = [row for row in outdated if row[0].source == "nexus"]

    if thunderstore_updates:
        auto = app.conf["auto_update"]
        if auto or ui.confirm("Update %s from Thunderstore?" % ui.plural(
                len(thunderstore_updates), "mod"), True):
            for mod, current, latest, package in thunderstore_updates:
                if package is None:
                    continue
                try:
                    _apply_update(app, mod, package, current, latest)
                except (thunderstore.SourceError, mods_mod.InstallError) as error:
                    ui.fail("%s: %s" % (mod.id, error))
            app.invalidate()
    for mod, current, latest, _ in nexus_updates:
        _report_nexus(app, mod, current, latest)
    print()


def _manual_hint(app, manual, blocked=()):
    if blocked:
        ui.info("%s skipped - add a Nexus API key in /settings to check them."
                % ui.plural(len(blocked), "Nexus mod"))
        for mod in blocked:
            print("      " + ui.grey("%s  (nexus id %s)" % (mod.name or mod.id, mod.source_id)))
    if manual:
        ui.info("%s can't be version-checked (installed by hand, no source recorded)."
                % ui.plural(len(manual), "mod"))


# ================================================================ PROFILES

def cmd_profiles(app, args):
    """Switch, create, rename, delete and save profiles - one screen."""
    if not app.require_game():
        return

    if args:
        return _profile_words(app, args)
    if not picker.available():
        return _profile_listing(app)

    actions = {"n": "new", "r": "rename", "d": "delete", "s": "save"}
    footer = ("↑↓ move   enter switch   n new   r rename   s save here   "
              "d delete   q quit")

    while True:
        installed = app.mods(refresh=True)
        dirty = app.profiles.modified(installed)
        rows = []
        for name in app.profiles.names:
            disabled = app.profiles.disabled(name)
            on = sum(1 for m in installed if m.id not in disabled)
            meta = "%d of %d on" % (on, len(installed))
            if name == app.profiles.active and dirty:
                meta += "   unsaved changes"
            rows.append(picker.Row(name, meta,
                                   checked=name == app.profiles.active, payload=name))

        header = (ui.bold(ui.white("Profiles")) + ui.grey("  ·  ")
                  + ui.grey("active: " + app.profiles.active))
        result = picker.manage(header, rows, actions, footer)
        if result is None:
            return

        kind = result[0]
        row = result[-1]
        if kind == "select":
            if row.payload == app.profiles.active and not dirty:
                ui.info("Already on %s." % row.payload)
                return
            return _switch_to(app, row.payload)

        key = result[1]
        try:
            if key == "n":
                name = ui.ask("Name for the new profile (from the current mods)")
                if name:
                    created = app.profiles.create(name, app.mods())
                    ui.good("Created %s and switched to it." % created)
            elif key == "r":
                name = ui.ask("New name for %s" % row.payload, row.payload)
                if name and name != row.payload:
                    ui.good("Renamed to %s." % app.profiles.rename(row.payload, name))
            elif key == "s":
                if ui.confirm("Save the current mods into %s?" % ui.bold(row.payload), True):
                    app.profiles.store(row.payload, app.mods(refresh=True))
                    ui.good("Saved into %s." % row.payload)
            elif key == "d":
                if ui.confirm("Delete profile %s?" % ui.bold(row.payload), False):
                    app.profiles.delete(row.payload)
                    ui.good("Deleted %s. Active is %s."
                            % (row.payload, app.profiles.active))
        except ProfileError as error:
            ui.fail(str(error))


def _switch_to(app, name):
    installed = app.mods(refresh=True)
    if app.profiles.modified(installed):
        off, on = app.profiles.drift(installed)
        ui.note("Profile %s has unsaved changes (%d off, %d on)."
                % (app.profiles.active, len(off), len(on)))
        question = ("Revert %s to its saved state?" % ui.bold(name)
                    if name == app.profiles.active
                    else "Discard them and switch to %s?" % ui.bold(name))
        if not ui.confirm(question, False):
            ui.info("Staying on %s." % app.profiles.active)
            return
    resolved, changed = app.profiles.switch(name, app.mods(refresh=True),
                                            app.conf.bepinex)
    app.invalidate()
    if not changed:
        ui.good("Switched to %s (already matching)." % resolved)
        return
    ui.good("Switched to %s." % resolved)
    for mod, enabled in changed:
        print("    " + ui.state(enabled) + " " + ui.grey(mod.name or mod.id))


def _profile_words(app, args):
    """Typed forms, kept for one-shot use: /profiles [create|delete|save|rename] ..."""
    action = args[0].lower()
    rest = args[1:]

    if action == "create":
        if not rest:
            return usage("/profiles create <name>")
        created = app.profiles.create(" ".join(rest), app.mods())
        ui.good("Created %s and switched to it." % created)
        return
    if action == "delete":
        if not rest:
            return usage("/profiles delete <name>")
        name = " ".join(rest)
        resolved = app.profiles.resolve(name)
        if resolved is None:
            raise ProfileError("No profile called '%s'." % name)
        if ui.confirm("Delete profile %s?" % ui.bold(resolved), False):
            app.profiles.delete(resolved)
            ui.good("Deleted %s. Active is %s." % (resolved, app.profiles.active))
        return
    if action == "save":
        saved = app.profiles.store(" ".join(rest) or app.profiles.active,
                                   app.mods(refresh=True))
        ui.good("Saved current mods into %s." % saved)
        return
    if action == "rename":
        if len(rest) < 2:
            return usage("/profiles rename <old> <new>")
        ui.good("Renamed to %s." % app.profiles.rename(rest[0], " ".join(rest[1:])))
        return

    name = " ".join(args)
    if app.profiles.resolve(name) is None:
        raise ProfileError("No profile called '%s'." % name)
    return _switch_to(app, name)


def _profile_listing(app):
    """Text fallback when there's no terminal to draw a picker on."""
    installed = app.mods(refresh=True)
    dirty = app.profiles.modified(installed)
    print()
    print(ui.header("Profiles"))
    print()
    for name in app.profiles.names:
        active = name == app.profiles.active
        marker = ui.accent(ui.ACTIVE) if active else " "
        suffix = ui.warn("  (unsaved changes)") if active and dirty else ""
        print("%s %s%s" % (marker, ui.bold(ui.white(name)) if active
                           else ui.white(name), suffix))
        disabled = app.profiles.disabled(name)
        for mod in installed:
            enabled = mod.id not in disabled
            label = ui.truncate(mod.name or mod.id, 40)
            print("  " + ui.state(enabled) + " "
                  + (ui.white(label) if enabled else ui.grey(label)))
        print()
    print(ui.grey("%s = active profile   %s = enabled   %s = disabled"
                  % (ui.ACTIVE, ui.ON, ui.OFF)))
    print()


# ==================================================================== GAME

def cmd_launch(app, args):
    if not app.require_game():
        return
    if game_mod.is_running():
        ui.note("Silksong already looks like it's running.")
        if not ui.confirm("Launch anyway?", False):
            return

    installed = app.mods(refresh=True)
    enabled = [m for m in installed if m.enabled]

    if app.conf["confirm_launch"]:
        print()
        ui.info("Profile %s with %s:" % (ui.bold(app.profiles.active),
                                         ui.plural(len(enabled), "mod")))
        for mod in enabled:
            print("    " + ui.ok(ui.ON) + " " + ui.grey(mod.id))
        print()
        if not ui.confirm("Launch Silksong?", True):
            return

    broken = [(m, deps_mod.missing(m, installed, app.conf)) for m in enabled]
    broken = [(m, gaps) for m, gaps in broken if gaps]
    if broken:
        for mod, gaps in broken:
            ui.note("%s is missing %s" % (mod.name or mod.id, ", ".join(
                thunderstore.split_dependency(g)[0] for g in gaps)))
        ui.info("Run /missing to see download links or install them.")
        if not ui.confirm("Launch anyway?", True):
            return

    if app.conf["backup_saves_on_launch"]:
        try:
            path, count = saves_mod.create(app.conf, app.profiles.active)
            ui.info("Saves backed up (%s) → %s" % (ui.plural(count, "file"), path.name))
        except OSError as error:
            ui.note("Couldn't back up saves: %s" % error)

    how = game_mod.launch(app.conf)
    ui.good("Launching Silksong via %s with %s."
            % (ui.grey(how), ui.plural(len(enabled), "mod")))
    ui.info("Check /logs once it's up if a mod doesn't load.")


def cmd_backup(app, args):
    """Snapshot the save folder, list snapshots, or restore one."""
    if not app.require_game():
        return
    action = args[0].lower() if args else "new"

    if action in ("ls", "list"):
        existing = saves_mod.snapshots()
        print()
        print(ui.header("Save backups"))
        print()
        if not existing:
            ui.info("No backups yet. /backup makes one.")
        for path, when, size in existing:
            print("  " + ui.white(ui.pad(path.stem.replace("saves_", ""), 26))
                  + ui.grey("%-10s %s" % (_bytes(size), _ago(time.time() - when))))
        print()
        ui.info(str(saves_mod.backup_dir()))
        print()
        return

    if action == "restore":
        existing = saves_mod.snapshots()
        if not existing:
            ui.fail("No backups to restore.")
            return
        if picker.available():
            rows = [picker.Row(path.stem.replace("saves_", ""),
                               "%s · %s" % (_bytes(size), _ago(time.time() - when)),
                               payload=path)
                    for path, when, size in existing]
            chosen = picker.choose(
                ui.bold(ui.white("Restore which backup?")), rows)
            if chosen is None:
                ui.info("Nothing restored.")
                return
            snapshot = chosen.payload
        else:
            snapshot = existing[0][0]
        ui.note("This overwrites your current saves.")
        if not ui.confirm("Restore %s?" % snapshot.stem, False):
            return
        safety = saves_mod.restore(app.conf, snapshot)
        ui.good("Restored %s." % snapshot.stem)
        ui.info("Your previous saves were kept as %s." % safety.stem)
        return

    label = " ".join(args) if args and action != "new" else app.profiles.active
    try:
        path, count = saves_mod.create(app.conf, label)
    except OSError as error:
        ui.fail(str(error))
        return
    ui.good("Backed up %s to %s." % (ui.plural(count, "save file"), path.name))


def _bytes(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return "%.0f %s" % (size, unit)
        size /= 1024.0
    return "%.1f TB" % size


def cmd_path(app, args):
    print()
    print(ui.header("Paths"))
    print()
    rows = [
        ("Silksong", app.conf["game_path"]),
        ("BepInEx", str(app.conf.bepinex) if app.conf.bepinex else ""),
        ("Downloads", app.conf["downloads_path"]),
        ("Wrapper", app.conf["wrapper_path"]),
        ("State", str(cfg.STATE_DIR)),
    ]
    for label, value in rows:
        if not value:
            print("    " + ui.pad(ui.white(label), 13) + ui.grey("not set"))
            continue
        exists = Path(value).exists()
        mark = ui.ok(ui.ON) if exists else ui.bad(ui.OFF)
        print("  " + mark + " " + ui.pad(ui.white(label), 13) + ui.grey(value))
    print()
    print("    " + ui.pad(ui.white("BepInEx"), 13)
          + (ui.ok("installed") if app.conf.bepinex_installed else ui.bad("not installed")))
    age = game_mod.log_age(app.conf)
    if age is not None:
        print("    " + ui.pad(ui.white("Last log"), 13) + ui.grey(_ago(age)))
    print()
    ui.info("Change these with /settings.")
    print()


def cmd_logs(app, args):
    if not app.require_game():
        return
    lines = 40
    only_errors = "--errors" in args or "-e" in args
    for arg in args:
        if arg.isdigit():
            lines = int(arg)
    path, content = game_mod.read_log(app.conf, lines, only_errors)
    if path is None:
        ui.fail("No BepInEx log yet. Launch the game once.")
        return
    print()
    print(ui.header("BepInEx log  " + ui.grey("· " + _ago(game_mod.log_age(app.conf) or 0))))
    print()
    if not content:
        ui.info("Nothing to show." + (" (no errors logged)" if only_errors else ""))
    for line in content:
        colour = ui.grey
        if "Error" in line or "Exception" in line or "Fatal" in line:
            colour = ui.bad
        elif "Warning" in line:
            colour = ui.warn
        elif "Loading [" in line or "Loaded " in line:
            colour = ui.white
        print("  " + colour(ui.truncate(line.rstrip(), ui.width() - 4)))
    print()
    ui.info(str(path))
    print()


def cmd_setup(app, args):
    print()
    print(ui.header("Setup"))
    print()

    # ---- game path
    if app.conf.configured and not ui.confirm(
            "Game already set to %s. Change it?" % ui.grey(app.conf["game_path"]), False):
        pass
    else:
        ui.info("Looking for Silksong...")
        installs = find_installs()
        chosen = None
        if installs:
            chosen = ui.choose("Use which install?", installs,
                               lambda i: "%s %s" % (ui.white(ui.truncate(str(i["game"]), 58)),
                                                    ui.grey(i["kind"])))
        if chosen is None:
            typed = ui.ask("Path to the 'Hollow Knight Silksong' folder (contains the .exe)",
                           app.conf["game_path"])
            if not typed:
                ui.fail("Setup cancelled - no game path.")
                return
            candidate = Path(typed.strip().strip('"').strip("'")).expanduser()
            if not (candidate / cfg.GAME_EXE).exists() and \
                    not (candidate / "Hollow Knight Silksong").exists():
                ui.note("No Silksong executable in there. Saving anyway.")
            chosen = {"game": candidate, "wrapper": _wrapper_for(candidate), "kind": "manual"}

        app.conf["game_path"] = str(chosen["game"])
        app.conf["bepinex_path"] = ""
        if chosen.get("wrapper"):
            app.conf["wrapper_path"] = str(chosen["wrapper"])
        ui.good("Game path: " + str(chosen["game"]))
        if chosen.get("wrapper"):
            ui.good("Launching through: " + chosen["wrapper"].name)

    # ---- downloads path
    if not Path(app.conf["downloads_path"]).is_dir():
        typed = ui.ask("Downloads folder", app.conf["downloads_path"])
        if typed:
            app.conf["downloads_path"] = str(Path(typed).expanduser())

    # ---- BepInEx
    print()
    if app.conf.bepinex_installed:
        ui.good("BepInEx is installed.")
    else:
        ui.note("BepInEx is not installed - mods won't load without it.")
        if ui.confirm("Install the BepInEx pack from Thunderstore?", True):
            _install_bepinex(app)

    # ---- adopt existing mods
    print()
    installed = app.mods(refresh=True)
    if installed:
        ui.good("Found %s already in the BepInEx folder." % ui.plural(len(installed), "mod"))
        known = mods_mod.load_registry()
        adopted = [m for m in installed if m.id not in known]
        if adopted:
            for mod in adopted:
                mods_mod.remember(mod)
            ui.good("Adopted %s (kept exactly as they are)."
                    % ui.plural(len(adopted), "existing mod"))
        app.profiles.store(app.profiles.active, installed)
        ui.good("Saved the current state as profile %s." % app.profiles.active)

    # ---- nexus
    print()
    if not nexus.configured(app.conf):
        nexus_like = [m for m in installed if m.source == "nexus"]
        if nexus_like:
            ui.info("%s look like Nexus downloads."
                    % ui.plural(len(nexus_like), "installed mod"))
        if ui.confirm("Add a Nexus Mods API key now? (optional, enables update checks)", False):
            _set_nexus_key(app)

    print()
    ui.good("Setup done. Try /toggle, /profiles or /launch.")
    print()


def _wrapper_for(game_path):
    """Walk up from a game folder to the .app wrapper that contains it."""
    for parent in game_path.parents:
        if parent.name.endswith(".app"):
            return parent
    return None


def _install_bepinex(app):
    package = mods_mod.find_bepinex_package(app.conf)
    if package is None:
        ui.fail("Couldn't find a BepInEx pack on Thunderstore. Install it manually.")
        return
    name = thunderstore.full_name(package)
    version = thunderstore.latest(package)
    with tempfile.TemporaryDirectory(prefix="beastfly-bep-") as scratch:
        archive = Path(scratch) / "bepinex.zip"
        thunderstore.download(package, archive, version,
                              on_progress=lambda d, t: ui.progress("BepInEx", d, t))
        ui.progress_done()
        written = mods_mod.install_bepinex(archive, app.conf)
    ui.good("Installed %s %s (%s)." % (name, version.get("version_number", ""),
                                       ui.plural(written, "file")))
    ui.info("Launch the game once so BepInEx can generate its config.")


# ================================================================ SETTINGS

TOGGLES = [
    ("INSTALLATION", [
        ("auto_install_deps", "Auto-install dependencies"),
        ("auto_enable_new", "Auto-enable new mods"),
        ("confirm_remove", "Confirm before removing"),
    ]),
    ("UPDATES", [
        ("check_updates", "Check for updates"),
        ("auto_update", "Auto-update mods"),
    ]),
    ("PROFILES", [
        ("remember_profile", "Remember active profile"),
    ]),
    ("GAME", [
        ("launch_via_porting_kit", "Launch through Porting Kit"),
        ("confirm_launch", "Confirm before launching"),
        ("backup_saves_on_launch", "Back up saves before launching"),
    ]),
    ("DISPLAY", [
        ("show_deps", "Show dependency information"),
        ("show_update_notifications", "Show update notifications"),
    ]),
]

PATH_ITEMS = [
    ("game_path", "Silksong path"),
    ("bepinex_path", "BepInEx path"),
    ("downloads_path", "Downloads path"),
]

INTEGRATION_ITEMS = [
    ("thunderstore_community", "Thunderstore community"),
    ("nexus_api_key", "Nexus Mods API key"),
]


def _settings_items(app):
    """Flatten the menu into an ordered list of (kind, key, label)."""
    items = []
    for _, entries in TOGGLES:
        for key, label in entries:
            items.append(("toggle", key, label))
    for key, label in PATH_ITEMS:
        items.append(("path", key, label))
    for key, label in INTEGRATION_ITEMS:
        items.append(("text", key, label))
    items.append(("reset", "", "Reset settings"))
    items.append(("back", "", "Back"))
    return items


def cmd_settings(app, args):
    items = _settings_items(app)

    # Non-interactive form: /settings auto_update on
    if args:
        return _settings_direct(app, args)

    while True:
        print()
        print(ui.header("Beastfly Settings", "─"))
        number = 0
        for title, entries in TOGGLES:
            print()
            print(ui.section("  " + title))
            for key, label in entries:
                number += 1
                value = ui.ok("ON") if app.conf[key] else ui.grey("OFF")
                print("  %s %s %s" % (ui.accent("[%2d]" % number),
                                      ui.white(label.ljust(30)), value))
        print()
        print(ui.section("  PATHS"))
        for key, label in PATH_ITEMS:
            number += 1
            shown = app.conf[key] or (str(app.conf.bepinex) if key == "bepinex_path"
                                      and app.conf.bepinex else "")
            display = ui.grey(ui.truncate(shown, ui.width() - 40)) if shown else ui.bad("not set")
            print("  %s %s %s" % (ui.accent("[%2d]" % number),
                                  ui.white(label.ljust(30)), display))
        print()
        print(ui.section("  INTEGRATIONS"))
        for key, label in INTEGRATION_ITEMS:
            number += 1
            raw = app.conf[key]
            if key == "nexus_api_key":
                display = (ui.ok("set") + ui.grey("  from " + nexus.key_source(app.conf))
                           if nexus.configured(app.conf) else ui.grey("not set"))
            else:
                display = ui.grey(raw or "not set")
            print("  %s %s %s" % (ui.accent("[%2d]" % number),
                                  ui.white(label.ljust(30)), display))
        print()
        print(ui.section("  OTHER"))
        for label in ("Reset settings", "Back"):
            number += 1
            print("  %s %s" % (ui.accent("[%2d]" % number), ui.white(label)))
        print()

        try:
            raw = input("  Enter a number to change:\n  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not raw:
            return
        if raw.lower() in ("q", "back", "exit"):
            return
        if not raw.isdigit() or not (1 <= int(raw) <= len(items)):
            ui.fail("Pick a number from 1 to %d." % len(items))
            continue

        kind, key, label = items[int(raw) - 1]
        if kind == "back":
            return
        if kind == "toggle":
            state = app.conf.toggle(key)
            ui.good("%s is now %s." % (label, "ON" if state else "OFF"))
        elif kind == "path":
            _edit_path(app, key, label)
        elif kind == "text":
            if key == "nexus_api_key":
                _set_nexus_key(app)
            else:
                typed = ui.ask("New value for " + label, app.conf[key])
                if typed:
                    app.conf[key] = typed
                    thunderstore._memory = None
                    ui.good("%s set to %s." % (label, typed))
        elif kind == "reset":
            if ui.confirm("Reset all settings to defaults? (paths and keys are kept)", False):
                app.conf.reset()
                ui.good("Settings reset.")


def _settings_direct(app, args):
    """/settings <key> [on|off|value] for scripting and muscle memory."""
    key = args[0].lower()
    known = {k for _, entries in TOGGLES for k, _ in entries}
    known |= {k for k, _ in PATH_ITEMS} | {k for k, _ in INTEGRATION_ITEMS}
    if key not in known:
        ui.fail("Unknown setting " + ui.bold(key) + ".")
        ui.info("Known: " + ", ".join(sorted(known)))
        return
    if len(args) == 1:
        ui.info("%s = %s" % (key, app.conf[key]))
        return
    value = " ".join(args[1:])
    if value.lower() in ("on", "true", "yes", "1"):
        app.conf[key] = True
    elif value.lower() in ("off", "false", "no", "0"):
        app.conf[key] = False
    else:
        app.conf[key] = value
    ui.good("%s = %s" % (key, app.conf[key]))


def _edit_path(app, key, label):
    typed = ui.ask("New " + label + " (blank to keep, '-' to clear)", app.conf[key])
    if typed is None:
        return
    if typed == "-":
        app.conf[key] = ""
        ui.good("%s cleared." % label)
        return
    path = Path(typed.strip().strip('"').strip("'")).expanduser()
    if not path.exists():
        ui.note("That path doesn't exist yet.")
        if not ui.confirm("Save it anyway?", False):
            return
    app.conf[key] = str(path)
    if key == "game_path":
        wrapper = _wrapper_for(path)
        if wrapper:
            app.conf["wrapper_path"] = str(wrapper)
            ui.good("Wrapper detected: " + wrapper.name)
        app.conf["bepinex_path"] = ""
    app.invalidate()
    ui.good("%s set to %s." % (label, path))


def _set_nexus_key(app):
    print()
    ui.info("Nexus -> your avatar -> Site Preferences -> API Keys tab:")
    ui.info("  " + ui.white("https://www.nexusmods.com/users/myaccount?tab=api"))
    ui.info("Ignore the long list of per-application keys at the top. Scroll to")
    ui.info("the bottom, generate the single " + ui.white("Personal API Key") + ", and paste it here.")
    ui.info("Or skip this and export $%s instead." % nexus.ENV_KEY)
    print()
    typed = ui.ask("Nexus API key (blank to keep, '-' to clear)")
    if typed is None:
        return
    if typed == "-":
        app.conf["nexus_api_key"] = ""
        ui.good("Nexus key cleared.")
        return
    key = nexus.clean_key(typed)
    if not key:
        ui.fail("Couldn't find a key in that.")
        return
    if key != typed.strip():
        ui.info("Trimmed the surrounding shell syntax off the paste.")
    app.conf["nexus_api_key"] = key
    ui.info("Stored in %s - keep that file out of git." % cfg.CONFIG_FILE)
    try:
        user = nexus.validate(app.conf)
        ui.good("Nexus key accepted (%s%s)." % (
            user.get("name", "ok"), ", premium" if user.get("is_premium") else ""))
        if not user.get("is_premium"):
            ui.info("Free accounts can't download via API - Beastfly will only check versions.")
    except nexus.NexusError as error:
        ui.fail(str(error))


# =================================================================== OTHER

def cmd_help(app, args):
    if args:
        name = args[0].lstrip("/").lower()
        entry = COMMANDS.get(name)
        if entry is None:
            ui.fail("No command " + ui.bold("/" + name) + ".")
            return
        print()
        print("  " + ui.accent("/" + name) + " " + ui.grey(entry[1]))
        print("  " + entry[2])
        if len(entry) > 4 and entry[4]:
            print()
            for line in entry[4]:
                print("  " + ui.grey(line))
        print()
        return

    print()
    print("  " + ui.bold(ui.accent("Beastfly")) + ui.grey(" — Silksong mod manager"))
    order = ["MODS", "PROFILES", "GAME", "OTHER"]
    for group in order:
        print()
        print(ui.section("  " + group))
        for name, entry in COMMANDS.items():
            if entry[3] != group or name in ALIASES or name in HIDDEN:
                continue
            invocation = "/" + name + (" " + entry[1] if entry[1] else "")
            print("  " + ui.pad(ui.accent(invocation), 28) + ui.grey(entry[2]))
            for sub_invocation, sub_text in SUBCOMMANDS.get(name, ()):
                print("  " + ui.pad(ui.accent(sub_invocation), 28) + ui.grey(sub_text))
    print()
    print(ui.section("  EXAMPLES"))
    for line in ["/toggle              turn mods on and off",
                 "/add all             install everything in Downloads",
                 "/profiles            switch profile",
                 "/launch              start the game"]:
        print("  " + ui.grey(line))
    print()


def cmd_clear(app, args):
    os.system("clear")
    print()
    print(ui.title())
    print()


def cmd_exit(app, args):
    if app.conf["remember_profile"]:
        app.profiles.save()
    app.running = False
    print(ui.grey("  Bye."))


def usage(text):
    ui.info("Usage: " + text)


def _wrap(text, width):
    words, lines, current = str(text).split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        lines.append(current)
    return lines[:6]


def _human_size(path):
    try:
        size = path.stat().st_size if path.is_file() else 0
    except OSError:
        return ""
    if not size:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return "%.0f %s" % (size, unit)
        size /= 1024.0
    return "%.1f TB" % size


def _ago(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return "%ds ago" % seconds
    if seconds < 3600:
        return "%dm ago" % (seconds // 60)
    if seconds < 86400:
        return "%dh ago" % (seconds // 3600)
    return "%dd ago" % (seconds // 86400)


# Extra lines rendered under a command in /help.
SUBCOMMANDS = {
    "profiles": (
        ("/profiles <name>", "Switch straight to a profile"),
    ),
}

# name -> (handler, args, description, group, [extra help lines])
COMMANDS = {
    "toggle":   (cmd_toggle, "", "Turn mods on and off", "MODS",
                 ["Arrow keys and space, or /toggle <mod> to flip one."]),
    "add":      (cmd_add, "", "Install mods", "MODS",
                 ["/add            pick from Downloads in a list",
                  "/add all        install everything in Downloads",
                  "/add <name>     from Downloads or Thunderstore"]),
    "remove":   (cmd_remove, "<mod>", "Uninstall a mod", "MODS"),
    "info":     (cmd_info, "<mod>", "Mod details and dependency tree", "MODS"),
    "updates":  (cmd_updates, "", "Check for updates and install them", "MODS"),
    "missing":  (cmd_missing, "", "Find and fix unmet dependencies", "MODS"),

    "profiles": (cmd_profiles, "", "Switch, create, rename, delete profiles",
                 "PROFILES",
                 ["Arrow keys; n new, r rename, s save, d delete.",
                  "/profiles <name> switches straight to one."]),

    "launch":   (cmd_launch, "", "Launch Silksong", "GAME"),
    "backup":   (cmd_backup, "", "Snapshot your save files", "GAME",
                 ["/backup           make one now",
                  "/backup list      show what you have",
                  "/backup restore   put one back"]),
    "logs":     (cmd_logs, "", "Show the BepInEx log", "GAME",
                 ["/logs 100      last 100 lines",
                  "/logs --errors errors and warnings only"]),
    "setup":    (cmd_setup, "", "Configure paths, BepInEx and API keys", "GAME"),

    "settings": (cmd_settings, "", "Open settings", "OTHER"),
    "help":     (cmd_help, "", "Show this help", "OTHER"),
    "clear":    (cmd_clear, "", "Clear the terminal", "OTHER"),
    "exit":     (cmd_exit, "", "Exit Beastfly", "OTHER"),
}

# Real commands kept out of /help: scripts and muscle memory still want them,
# but the visible list stays short. /enable and /disable are deliberately not
# aliases of /toggle - they set an absolute state, which is what a script needs.
HIDDEN = {
    "ls":       (cmd_ls, "", "List installed mods as text", "MODS",
                 ["--enabled / --disabled to filter"]),
    "enable":   (cmd_enable, "<mod>", "Enable a mod by name", "MODS"),
    "disable":  (cmd_disable, "<mod>", "Disable a mod by name", "MODS"),
    "search":   (cmd_search, "<query>", "Search Thunderstore", "MODS"),
    "path":     (cmd_path, "", "Show configured paths", "GAME"),
}
COMMANDS.update(HIDDEN)

ALIASES = {
    "list": "ls", "quit": "exit", "q": "exit", "install": "add",
    "uninstall": "remove", "rm": "remove", "find": "search", "?": "help",
    "fix": "missing", "doctor": "missing", "mods": "toggle", "m": "toggle",
    "t": "toggle", "switch": "profiles", "sw": "profiles",
    "profile": "profiles", "deps": "info", "update": "updates",
}
for alias, target in ALIASES.items():
    COMMANDS[alias] = COMMANDS[target]


def _label_for(installed):
    """Shortest string per mod that find() will resolve back to that same mod."""
    counts = {}
    for mod in installed:
        key = (mod.name or mod.id).lower()
        counts[key] = counts.get(key, 0) + 1
    labels = {}
    for mod in installed:
        name = mod.name or mod.id
        labels[mod.id] = name if counts[name.lower()] == 1 else mod.id
    return labels


def _installable_downloads(app):
    """Things in the Downloads folder that actually contain mod assemblies.

    A Downloads folder is full of unrelated archives, so a .zip extension is
    not enough - each candidate is opened and must hold a .dll or a
    manifest.json to be offered. Returns [(path, description)], newest first.
    """
    folder = app.conf.downloads
    if not folder.is_dir():
        return []
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []

    # Never offer the game itself, or the wrapper it lives inside.
    excluded = set()
    for candidate in (app.conf.game, app.conf.wrapper, app.conf.bepinex):
        if candidate:
            excluded.add(candidate.resolve())
            excluded.update(parent.resolve() for parent in candidate.parents)

    items = []
    for path in entries:
        try:
            if path.resolve() in excluded:
                continue
        except OSError:
            continue
        description = mods_mod.describe_archive(path)
        if description is None:
            continue
        try:
            items.append((path, description, path.stat().st_mtime))
        except OSError:
            continue
    items.sort(key=lambda row: -row[2])
    return [(path, description) for path, description, _ in items[:60]]


def arg_provider(app):
    """Completion for a command's argument: mod names, profiles, downloads.

    Runs on every keystroke, so it never makes a network call - Thunderstore is
    consulted only if its listing is already cached.
    """
    downloads_cache = {"stamp": 0.0, "items": []}

    def mod_rows(command, partial):
        installed = app.mods()
        found = mods_mod.find(installed, partial) if partial.strip() else installed
        labels = _label_for(installed)
        rows = []
        for mod in found[:20]:
            meta = " ".join(x for x in (mod.version, mod.source) if x)
            rows.append(prompt_mod.Entry(
                "%s %s" % (ui.ON if mod.enabled else ui.OFF, labels[mod.id]),
                meta,
                insert="/%s %s" % (command, labels[mod.id])))
        return rows

    def profile_rows(command, partial):
        folded = partial.strip().lower()
        rows = []
        for name in app.profiles.names:
            if folded and folded not in name.lower():
                continue
            active = " (active)" if name == app.profiles.active else ""
            rows.append(prompt_mod.Entry(
                name, "profile" + active, insert="/%s %s" % (command, name)))
        return rows

    def download_rows(command, partial):
        now = time.time()
        if now - downloads_cache["stamp"] > 5:
            downloads_cache["items"] = _installable_downloads(app)
            downloads_cache["stamp"] = now
        folded = mods_mod._norm(partial)
        rows = []
        for path, description in downloads_cache["items"]:
            if folded and folded not in mods_mod._norm(path.name):
                continue
            rows.append(prompt_mod.Entry(
                ui.truncate(path.name, 30), "Downloads · " + description,
                insert="/%s %s" % (command, path.name)))
            if len(rows) >= 12:
                break
        if folded and len(folded) >= 2:
            for package in thunderstore.cached(app.conf):
                if len(rows) >= 20:
                    break
                if folded in mods_mod._norm(package.get("name", "")):
                    rows.append(prompt_mod.Entry(
                        package["name"],
                        "Thunderstore " + thunderstore.version_of(package),
                        insert="/%s %s" % (command, package["name"])))
        return rows

    def provide(command, partial):
        entry = COMMANDS.get(command.lower())
        if entry is None:
            return []
        canonical = ALIASES.get(command.lower(), command.lower())
        if canonical == "add":
            return download_rows(command, partial)
        if canonical == "profiles":
            return profile_rows(command, partial)
        if canonical == "toggle" or "<mod>" in entry[1]:
            return mod_rows(command, partial)
        return []

    return provide


def menu_entries():
    """Rows for the slash menu: the visible commands, plus listed subcommands."""
    entries = []
    for name, entry in COMMANDS.items():
        if name in ALIASES or name in HIDDEN:
            continue
        entries.append(prompt_mod.Entry.command(name, entry[1], entry[2]))
    for subs in SUBCOMMANDS.values():
        for invocation, description in subs:
            words = invocation.lstrip("/").split()
            if len(words) < 2 or words[1].startswith("<"):
                continue
            entries.append(prompt_mod.Entry.command(
                " ".join(words[:2]), " ".join(words[2:]), description))
    entries.sort(key=lambda e: e.key)
    return entries


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    app = App()

    if argv and argv[0] in ("-h", "--help"):
        cmd_help(app, [])
        return 0
    if argv and argv[0] in ("-v", "--version", "about"):
        print()
        print("  " + ui.bold(ui.accent("beastfly")) + ui.grey(" " + ui.VERSION))
        print("  " + ui.grey("A CLI mod manager for Hollow Knight: Silksong."))
        print("  " + ui.grey("Built for running the Windows build on macOS"))
        print("  " + ui.grey("through Porting Kit, where the GUI managers"))
        print("  " + ui.grey("can't see your install."))
        print()
        print(ui.field("Python", "%d.%d.%d" % sys.version_info[:3], 10))
        print(ui.field("State", str(cfg.STATE_DIR), 10))
        print(ui.field("Game", app.conf["game_path"] or "not configured", 10))
        print()
        print("  " + ui.grey("MIT licensed. Named after the little grub-fly"))
        print("  " + ui.grey("that will not stop bothering you in Bone Bottom."))
        print()
        return 0

    if argv:
        # One-shot mode: beastfly ls, beastfly launch, ...
        app.dispatch(" ".join(argv))
        return 0

    if not app.conf.configured:
        print()
        print(ui.title())
        print()
        ui.note("No Silksong install configured yet.")
        installs = find_installs()
        if installs and ui.confirm("Found %s. Run setup now?"
                                   % ui.plural(len(installs), "install"), True):
            cmd_setup(app, [])
        app.repl()
        return 0

    app.repl()
    return 0
