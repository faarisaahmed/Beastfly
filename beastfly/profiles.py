"""Profiles: named enabled/disabled snapshots over one shared mod install.

Switching profiles does not move files around. Every profile sees the same
installed mods and only disagrees about which are switched on, which keeps
BepInEx configs, caches and save data in one place.
"""

import json
import time

from . import config as cfg
from . import mods as mods_mod

PROFILES_FILE = cfg.STATE_DIR / "profiles.json"
DEFAULT_NAME = "Default"
RESERVED = {"create", "delete", "save", "rename", "list"}


class ProfileError(Exception):
    pass


class Profiles:
    def __init__(self):
        self.active = DEFAULT_NAME
        self.data = {}
        self.load()

    # ---------- persistence ----------

    def load(self):
        if PROFILES_FILE.exists():
            try:
                stored = json.loads(PROFILES_FILE.read_text())
                self.active = stored.get("active") or DEFAULT_NAME
                self.data = stored.get("profiles") or {}
            except (ValueError, OSError):
                pass
        if not self.data:
            self.data = {DEFAULT_NAME: {"disabled": [], "created": time.time()}}
            self.active = DEFAULT_NAME

    def save(self):
        cfg.STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PROFILES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"active": self.active, "profiles": self.data}, indent=2, sort_keys=True))
        tmp.replace(PROFILES_FILE)

    # ---------- queries ----------

    @property
    def names(self):
        """Active profile first, then the rest alphabetically."""
        rest = sorted((n for n in self.data if n != self.active), key=str.lower)
        return ([self.active] if self.active in self.data else []) + rest

    def exists(self, name):
        return self.resolve(name) is not None

    def resolve(self, name):
        """Case-insensitive lookup, so /profile multiplayer works."""
        if name in self.data:
            return name
        lowered = name.lower()
        for existing in self.data:
            if existing.lower() == lowered:
                return existing
        return None

    def disabled(self, name):
        return set(self.data.get(name, {}).get("disabled") or [])

    def is_enabled(self, name, mod_id):
        return mod_id not in self.disabled(name)

    # ---------- mutation ----------

    def snapshot(self, mods):
        """The current on-disk state as a disabled-id list."""
        return sorted(m.id for m in mods if not m.enabled)

    def create(self, name, mods):
        name = name.strip()
        if not name:
            raise ProfileError("Give the profile a name.")
        if name.lower() in RESERVED:
            raise ProfileError("'%s' is a reserved word. Pick another name." % name)
        if self.exists(name):
            raise ProfileError("Profile '%s' already exists." % name)
        self.data[name] = {"disabled": self.snapshot(mods), "created": time.time()}
        # A new profile is made *from* the live state, so it is already applied -
        # become active, otherwise later toggles would keep editing the old one.
        self.active = name
        self.save()
        return name

    def delete(self, name):
        resolved = self.resolve(name)
        if resolved is None:
            raise ProfileError("No profile called '%s'." % name)
        if len(self.data) == 1:
            raise ProfileError("Can't delete the only profile.")
        del self.data[resolved]
        if self.active == resolved:
            self.active = self.names[0]
        self.save()
        return resolved

    def rename(self, old, new):
        resolved = self.resolve(old)
        if resolved is None:
            raise ProfileError("No profile called '%s'." % old)
        if self.exists(new):
            raise ProfileError("Profile '%s' already exists." % new)
        self.data[new] = self.data.pop(resolved)
        if self.active == resolved:
            self.active = new
        self.save()
        return new

    def store(self, name, mods):
        """Overwrite a profile with the current on-disk state."""
        resolved = self.resolve(name) or name.strip()
        if resolved.lower() in RESERVED:
            raise ProfileError("'%s' is a reserved word. Pick another name." % resolved)
        entry = self.data.setdefault(resolved, {"created": time.time()})
        entry["disabled"] = self.snapshot(mods)
        self.save()
        return resolved

    def switch(self, name, mods, bepinex=None):
        """Apply a profile to disk. Returns (profile, [(mod, enabled)] changed)."""
        resolved = self.resolve(name)
        if resolved is None:
            raise ProfileError("No profile called '%s'." % name)
        disabled = self.disabled(resolved)
        changed = []
        for mod in mods:
            wanted = mod.id not in disabled
            if wanted != mod.enabled:
                mods_mod.set_enabled(mod, wanted, bepinex)
                changed.append((mod, wanted))
        self.active = resolved
        self.save()
        return resolved, changed

    # ---------- drift ----------
    #
    # The active profile is a *saved snapshot*, not a live mirror. Toggling mods
    # drifts from it until you /profiles save, which is what makes it possible to
    # experiment and then switch back to recover a known-good set.

    def drift(self, mods):
        """(newly_disabled, newly_enabled) relative to the active profile."""
        if self.active not in self.data:
            return [], []
        saved = self.disabled(self.active)
        live = set(self.snapshot(mods))
        known = {m.id for m in mods}
        # Ignore ids for mods that no longer exist on disk.
        saved &= known
        return sorted(live - saved), sorted(saved - live)

    def modified(self, mods):
        disabled_now, enabled_now = self.drift(mods)
        return bool(disabled_now or enabled_now)

    def scope_to_active(self, mod_id, enabled=True):
        """A freshly installed mod belongs to the profile that installed it.

        Without this, every saved profile would silently inherit new mods,
        because a profile only records what is *disabled*.
        """
        for name, entry in self.data.items():
            disabled = list(entry.get("disabled") or [])
            if name == self.active:
                if enabled:
                    disabled = [d for d in disabled if d != mod_id]
                elif mod_id not in disabled:
                    disabled.append(mod_id)
            elif mod_id not in disabled:
                disabled.append(mod_id)
            entry["disabled"] = sorted(disabled)
        self.save()

    def drop_mod(self, mod_id):
        """Forget a removed mod everywhere."""
        touched = False
        for entry in self.data.values():
            disabled = entry.get("disabled") or []
            if mod_id in disabled:
                entry["disabled"] = [d for d in disabled if d != mod_id]
                touched = True
        if touched:
            self.save()
