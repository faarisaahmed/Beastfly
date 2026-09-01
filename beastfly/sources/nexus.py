"""Nexus Mods: version checks and mod metadata.

Nexus gates file downloads behind Premium plus an nxm:// handshake, so
Beastfly does not pretend to install from here. What it does do is tell you
when a Nexus mod you installed by hand has a newer version, and hand you the
page to grab it from. Needs a personal API key (Nexus account -> Site
Preferences -> API Keys).
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

from .. import config as cfg

API = "https://api.nexusmods.com/v1"
MOD_PAGE = "https://www.nexusmods.com/%s/mods/%s"
USER_AGENT = "beastfly/0.1 (+silksong mod manager)"
CACHE_TTL = 6 * 3600

# Nexus names downloads "<Mod Name>-<mod id>-<version with dots as dashes>-<unix ts>",
# e.g. "ShowDamage HealthBar-28-2-0-4-1758980847".
FOLDER_PATTERN = re.compile(
    r"^(?P<name>.+?)-(?P<mod_id>\d+)-(?P<version>\d+(?:-\d+)*)-(?P<stamp>\d{9,11})$"
)


class NexusError(Exception):
    pass


def parse_folder_name(name):
    """Recover the Nexus mod id and version from a downloaded folder/file name."""
    name = re.sub(r"\.(zip|7z|rar|dll)$", "", name.strip(), flags=re.I)
    match = FOLDER_PATTERN.match(name)
    if not match:
        return None
    return {
        "name": match.group("name").strip(),
        "mod_id": int(match.group("mod_id")),
        "version": match.group("version").replace("-", "."),
        "uploaded": int(match.group("stamp")),
    }


ENV_KEY = "BEASTFLY_NEXUS_API_KEY"

SEARCH_URL = "https://www.nexusmods.com/%s/search/?gsearch=%s&gsearchtype=mods"


# Someone pasting a key will often paste the whole shell line around it.
_ASSIGNMENT = re.compile(r'^\s*(?:export\s+)?(?:[A-Z][A-Z0-9_]*)\s*=\s*')


def clean_key(raw):
    """Pull the key out of whatever got pasted.

    Tolerates `export NAME="key"`, surrounding quotes, and line breaks from a
    wrapped copy. Nexus keys are base64-ish, so no legitimate key contains
    whitespace or quote characters.
    """
    key = (raw or "").strip()
    key = _ASSIGNMENT.sub("", key)
    key = key.strip().strip('"').strip("'")
    return "".join(key.split())


def api_key(conf):
    """The environment wins, so a shared config file never has to hold a key."""
    return clean_key(os.environ.get(ENV_KEY, "")) or clean_key(conf["nexus_api_key"])


def key_source(conf):
    if os.environ.get(ENV_KEY, "").strip():
        return "environment ($%s)" % ENV_KEY
    if conf["nexus_api_key"]:
        return "config file"
    return ""


def configured(conf):
    return bool(api_key(conf))


def search_url(conf, query):
    from urllib.parse import quote
    return SEARCH_URL % (conf["nexus_game_slug"], quote(query))


def page_url(conf, mod_id):
    return MOD_PAGE % (conf["nexus_game_slug"], mod_id)


def _cache_file(slug, mod_id):
    return cfg.CACHE_DIR / ("nexus-%s-%s.json" % (slug, mod_id))


def _request(conf, path, timeout=25):
    key = api_key(conf)
    if not key:
        raise NexusError("No Nexus API key set. Add one in /settings.")
    request = urllib.request.Request(API + path, headers={
        "apikey": key,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise NexusError("Nexus rejected the API key (401). Re-enter it in /settings.")
        if error.code == 404:
            raise NexusError("Not found on Nexus (404). Check the game slug in /settings.")
        if error.code == 429:
            raise NexusError("Nexus rate limit reached. Try again later.")
        raise NexusError("Nexus error %s." % error.code)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise NexusError("Could not reach Nexus (%s)." % error)


def validate(conf):
    """Confirm the key works. Returns the Nexus user record."""
    return _request(conf, "/users/validate.json")


def mod_info(conf, mod_id, use_cache=True):
    """Metadata for one mod, cached so /updates over many mods stays cheap."""
    slug = conf["nexus_game_slug"]
    cache = _cache_file(slug, mod_id)
    if use_cache and cache.exists() and (time.time() - cache.stat().st_mtime) < CACHE_TTL:
        try:
            return json.loads(cache.read_text())
        except (ValueError, OSError):
            pass
    data = _request(conf, "/games/%s/mods/%s.json" % (slug, mod_id))
    cfg.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        cache.write_text(json.dumps(data))
    except OSError:
        pass
    return data


def latest_version(conf, mod_id):
    return (mod_info(conf, mod_id) or {}).get("version", "")
