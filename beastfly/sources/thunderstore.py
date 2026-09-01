"""Thunderstore: the Silksong community package index.

The whole community listing is one gzipped request (~2 MB, a few hundred
packages), so we grab it wholesale and cache it rather than querying per mod.
"""

import gzip
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import config as cfg

BASE = "https://thunderstore.io/c/%s/api/v1/package/"
PACKAGE_PAGE = "https://thunderstore.io/c/%s/p/%s/%s/"
CACHE_TTL = 6 * 3600
USER_AGENT = "beastfly/0.1 (+silksong mod manager)"

_memory = None


class SourceError(Exception):
    pass


def _cache_file(community):
    return cfg.CACHE_DIR / ("thunderstore-%s.json" % community)


def _get(url, timeout=45):
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw


def fetch(conf, force=False, quiet=True):
    """All packages for the configured community. Falls back to cache offline."""
    global _memory
    community = conf["thunderstore_community"]
    cache = _cache_file(community)

    if _memory is not None and not force:
        return _memory

    fresh = cache.exists() and (time.time() - cache.stat().st_mtime) < CACHE_TTL
    if fresh and not force:
        try:
            _memory = json.loads(cache.read_text())
            return _memory
        except (ValueError, OSError):
            pass

    try:
        raw = _get(BASE % community)
        packages = json.loads(raw.decode("utf-8"))
        cfg.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(packages))
        _memory = packages
        return _memory
    except (urllib.error.URLError, OSError, ValueError) as error:
        if cache.exists():
            try:
                _memory = json.loads(cache.read_text())
                return _memory
            except (ValueError, OSError):
                pass
        raise SourceError("Could not reach Thunderstore (%s)." % error)


def cached(conf):
    """Whatever listing we already have, without ever hitting the network.

    Used for keystroke-time completion, where blocking on a request is worse
    than offering nothing.
    """
    global _memory
    if _memory is not None:
        return _memory
    cache = _cache_file(conf["thunderstore_community"])
    if cache.exists():
        try:
            _memory = json.loads(cache.read_text())
            return _memory
        except (ValueError, OSError):
            pass
    return []


def latest(package):
    versions = package.get("versions") or []
    return versions[0] if versions else None


def version_of(package):
    version = latest(package)
    return version.get("version_number", "") if version else ""


def full_name(package):
    return package.get("full_name") or "%s-%s" % (package.get("owner", ""), package.get("name", ""))


def download_url(package, version=None):
    version = version or latest(package)
    return version.get("download_url") if version else None


def dependencies(package, version=None):
    version = version or latest(package)
    if not version:
        return []
    return [d for d in version.get("dependencies") or [] if d and d.strip()]


def split_dependency(dependency):
    """'Owner-Name-1.2.3' -> ('Owner-Name', '1.2.3'). Names may contain dashes."""
    parts = dependency.rsplit("-", 1)
    if len(parts) == 2 and any(c.isdigit() for c in parts[1]):
        return parts[0], parts[1]
    return dependency, ""


def index(conf):
    """Map of lowercase 'Owner-Name' -> package."""
    return {full_name(p).lower(): p for p in fetch(conf)}


def by_full_name(conf, name):
    return index(conf).get(name.lower())


def by_dependency(conf, dependency):
    key, _ = split_dependency(dependency)
    return by_full_name(conf, key)


def search(conf, query, limit=25):
    """Rank packages by how well they match a free-text query."""
    query = query.strip().lower()
    if not query:
        return []
    scored = []
    for package in fetch(conf):
        if package.get("is_deprecated"):
            continue
        name = (package.get("name") or "").lower()
        owner = (package.get("owner") or "").lower()
        version = latest(package) or {}
        description = (version.get("description") or "").lower()

        if query == name:
            score = 0
        elif name.startswith(query):
            score = 1
        elif query in name:
            score = 2
        elif query in owner:
            score = 3
        elif query in description:
            score = 4
        else:
            continue
        # Break ties by popularity so the obvious pick floats up.
        scored.append((score, -package.get("rating_score", 0),
                       -(version.get("downloads") or 0), package))
    scored.sort(key=lambda row: row[:3])
    return [row[3] for row in scored[:limit]]


def download(package, destination, version=None, on_progress=None):
    """Stream a package zip to `destination`."""
    url = download_url(package, version)
    if not url:
        raise SourceError("No download available for %s." % full_name(package))
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(destination, "wb") as handle:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
    except (urllib.error.URLError, OSError) as error:
        raise SourceError("Download failed: %s" % error)
    return destination
