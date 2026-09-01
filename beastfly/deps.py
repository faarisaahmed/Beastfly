"""Dependency resolution and the dependency tree shown by /info.

Dependency strings come from Thunderstore manifests in the form
'Owner-Name-1.2.3'. BepInEx is special-cased: it is a loader, not a plugin,
so its presence is judged by the BepInEx tree rather than the mod list.
"""

from urllib.parse import quote

from .sources import nexus, thunderstore

BEPINEX_MARKERS = ("bepinex-bepinexpack", "bepinexpack", "bepinex")


def is_bepinex(dependency):
    key, _ = thunderstore.split_dependency(dependency)
    return key.lower().replace("_", "-") in BEPINEX_MARKERS or "bepinexpack" in key.lower()


def installed_index(mods):
    """Every name a mod might be referred to by -> mod."""
    index = {}
    for mod in mods:
        keys = {mod.id, mod.name, mod.id.split("/")[-1]}
        if mod.source_id and "/" in mod.source_id:
            owner, name = mod.source_id.split("/", 1)
            keys.add("%s-%s" % (owner, name))
            keys.add(name)
        for key in keys:
            if key:
                index.setdefault(key.lower(), mod)
    return index


def resolve(dependency, index):
    key, version = thunderstore.split_dependency(dependency)
    mod = index.get(key.lower())
    if mod is None:
        # 'Owner-Name' may be installed under just 'Name'.
        tail = key.rsplit("-", 1)[-1]
        mod = index.get(tail.lower())
    return mod, key, version


def dependencies_of(mod, conf):
    """Declared dependencies, preferring the live manifest, then Thunderstore."""
    if mod.dependencies:
        return list(mod.dependencies)
    if mod.source == "thunderstore" and mod.source_id:
        try:
            owner, name = mod.source_id.split("/", 1)
            package = thunderstore.by_full_name(conf, "%s-%s" % (owner, name))
            if package:
                return thunderstore.dependencies(package)
        except thunderstore.SourceError:
            pass
    return []


def tree(mod, mods, conf, max_depth=6):
    """Build a nested tree: {'label', 'ok', 'note', 'children'}."""
    index = installed_index(mods)

    def build(current, depth, seen):
        node_children = []
        if depth >= max_depth:
            return node_children
        for dependency in dependencies_of(current, conf):
            if is_bepinex(dependency):
                node_children.append({
                    "label": "BepInEx",
                    "ok": conf.bepinex_installed,
                    "note": "" if conf.bepinex_installed else "not installed",
                    "children": [],
                })
                continue
            resolved, key, version = resolve(dependency, index)
            if resolved is None:
                node_children.append({
                    "label": key,
                    "ok": False,
                    "note": "missing" + (" (wants %s)" % version if version else ""),
                    "children": [],
                })
                continue
            note = ""
            if not resolved.enabled:
                note = "installed but disabled"
            if key.lower() in seen:
                node_children.append({"label": resolved.id, "ok": resolved.enabled,
                                      "note": note or "circular", "children": []})
                continue
            node_children.append({
                "label": resolved.id,
                "ok": resolved.enabled,
                "note": note,
                "children": build(resolved, depth + 1, seen | {key.lower()}),
            })
        return node_children

    return {
        "label": mod.id,
        "ok": mod.enabled,
        "note": "" if mod.enabled else "disabled",
        "children": build(mod, 0, {mod.id.lower()}),
    }


def missing(mod, mods, conf):
    """Dependency keys that are not installed at all."""
    index = installed_index(mods)
    gaps = []
    for dependency in dependencies_of(mod, conf):
        if is_bepinex(dependency):
            continue
        resolved, key, _ = resolve(dependency, index)
        if resolved is None:
            gaps.append(dependency)
    return gaps


def available(dependency, conf):
    """The Thunderstore package satisfying a dependency, if there is one."""
    try:
        return thunderstore.by_dependency(conf, dependency)
    except thunderstore.SourceError:
        return None


def links(dependency, conf, package=None):
    """Where to get a dependency. Direct page if known, else search links."""
    key, _ = thunderstore.split_dependency(dependency)
    if package is None:
        package = available(dependency, conf)
    if package and package.get("package_url"):
        return [("Thunderstore", package["package_url"])]
    # Unknown to Thunderstore: hand over searches on both sites. Dependency
    # keys are 'Owner-Name', and the name is the useful half of that.
    term = key.rsplit("-", 1)[-1] if "-" in key else key
    return [
        ("Thunderstore search",
         "https://thunderstore.io/c/%s/?q=%s" % (conf["thunderstore_community"], quote(term))),
        ("Nexus search", nexus.search_url(conf, term)),
    ]


def audit(mods, conf):
    """Every mod with unmet dependencies.

    Returns [(mod, [{dependency, key, wanted, package}])], mods with gaps only.
    """
    index = installed_index(mods)
    report = []
    for mod in mods:
        gaps = []
        for dependency in dependencies_of(mod, conf):
            if is_bepinex(dependency):
                if not conf.bepinex_installed:
                    gaps.append({"dependency": dependency, "key": "BepInEx",
                                 "wanted": "", "package": None})
                continue
            resolved, key, wanted = resolve(dependency, index)
            if resolved is None:
                gaps.append({"dependency": dependency, "key": key,
                             "wanted": wanted, "package": available(dependency, conf)})
        if gaps:
            report.append((mod, gaps))
    return report
