# Beastfly

[![release](https://img.shields.io/github/v/release/faarisaahmed/Beastfly?label=release)](https://github.com/faarisaahmed/Beastfly/releases/latest)
[![downloads](https://img.shields.io/github/downloads/faarisaahmed/Beastfly/total)](https://github.com/faarisaahmed/Beastfly/releases)
[![ci](https://github.com/faarisaahmed/Beastfly/actions/workflows/ci.yml/badge.svg)](https://github.com/faarisaahmed/Beastfly/actions/workflows/ci.yml)

A terminal mod manager for **Hollow Knight: Silksong**, built for the awkward
case: running the **Windows** build on **macOS** through **Porting Kit**
(Wineskin), where the GUI managers can't see your install.

Pure Python 3, standard library only. No pip, no build step.

## Install

Grab the [latest release](https://github.com/faarisaahmed/Beastfly/releases/latest):

```sh
curl -fsSL https://github.com/faarisaahmed/Beastfly/releases/latest/download/beastfly-0.1.0.tar.gz | tar xz
cd beastfly-0.1.0
./install.sh
beastfly
```

Or from a clone:

```sh
git clone https://github.com/faarisaahmed/Beastfly.git
cd Beastfly && ./install.sh
```

`install.sh` drops a `beastfly` launcher in `~/.local/bin` and writes nothing
else. All state lives in `~/.beastfly/`, so the only thing Beastfly ever puts
in your game folder is mods. First run walks you through `/setup`, which
auto-detects your install.

Requires Python 3.8+ — macOS ships one. No other dependencies.

## Use

Run `beastfly` with no arguments for the interactive prompt. Four commands
cover almost everything, and none of them need you to type a mod name:

```
beastfly> /toggle      turn mods on and off in a list
beastfly> /profiles    switch, create, rename, delete profiles
beastfly> /add         pick what to install from Downloads
beastfly> /launch      start the game
```

Every command also works as a one-shot, which is handy for aliases:

```sh
beastfly ls
beastfly launch
beastfly updates
```

The leading `/` is optional. `/help` lists everything; `/help <command>` has
the detail.

### The slash menu

Type `/` and the command list opens just above the prompt, redrawing in place
as you type. `/pro` narrows to the profile commands; `/profile ` shows that
command's subcommands.

- **Up/Down** move the highlight
- **Tab** completes the highlighted row
- **Enter** runs it, or completes and waits if it takes arguments
- **Esc** closes the menu

The menu keeps going past the command name. Once a command that takes a mod is
typed, the rows become your installed mods with their state and version, so you
never have to type a folder name:

```
beastfly> /disable sdh
 ❯ ✓ ShowDamage HealthBar          2.0.4 nexus
```

`/add` offers matching files from your Downloads folder plus already-cached
Thunderstore packages; `/profile` offers your profile names. Completion never
makes a network call, so it can't stall between keystrokes.

### Naming mods

Mod folder names are frequently unusable —
`ShowDamage HealthBar-28-2-0-4-1758980847` is a Nexus artefact, not a name you
would ever type. So `<mod>` arguments match loosely, ignoring case, spaces and
punctuation, and fall back to initials:

| You type | It finds |
| --- | --- |
| `showdamage`, `show damage`, `healthbar` | ShowDamage HealthBar |
| `sdh` | ShowDamage HealthBar |
| `skip`, `skipintro` | Silksong skip intro |
| `toggle hud` | ToggleHUD |
| `qol` | all three mods in the `QoL/` group |

When more than one mod matches you get a numbered picker rather than a guess.

Up/Down with the menu closed walks back through command history. The usual
editing keys work too: Left/Right, Home/End, Ctrl-A/E/U/K/W, Ctrl-L to clear.

**Ctrl-C** with text on the line clears the line. On an empty line it warns,
and a second Ctrl-C quits. Ctrl-D on an empty line quits immediately, and
Ctrl-C during a running command just cancels that command.

The menu needs an interactive terminal. Piping commands in
(`echo /ls | beastfly`) falls back to plain line reading.

## The lists

`/toggle` opens a checklist of everything installed. Arrow keys move, space
toggles, enter saves:

```
Default  ·  9 mods installed

  ❯ [✓] CanvasUtil                           manual
    [✓] ShowDamage HealthBar                 2.0.4 nexus
    [✗] MapMod                               manual

↑↓ move   space toggle   a all   n none   i invert   enter save   q cancel
```

It writes straight to the active profile, so there is no save step to remember.
`a` checks everything, `n` clears it, `i` inverts, `q` cancels without touching
anything. `/toggle <mod>` flips a single mod without opening the list.

`/profiles` is the whole profile manager on one screen:

```
Profiles  ·  active: Default

  ❯ [✓] Default                              9 of 9 on
    [ ] Randomizer                           7 of 9 on
    [ ] Vanilla                              0 of 9 on

↑↓ move   enter switch   n new   r rename   s save here   d delete   q quit
```

Enter switches, `n` makes a new profile from whatever is enabled right now, `r`
renames, `s` saves the current mods into the highlighted profile, `d` deletes.
`/profiles <name>` switches straight to one without the list.

`/add` with nothing after it lists every installable thing in your Downloads
folder as a checklist, with anything not yet installed pre-checked. `/add all`
skips the list and installs the lot after one confirmation.

Mods installed this way belong to **the profile you were on**. Your other
profiles are saved snapshots and don't silently gain new mods. Automatically
installed *dependencies* are the exception — they stay enabled in every profile,
because a shared library switched off in one profile would quietly break
whatever needed it there.

## Commands

Thirteen commands, because the lists do the work:

| | |
| --- | --- |
| `/toggle` | Turn mods on and off. `/toggle <mod>` flips one. |
| `/add` | Install mods. `/add all` takes everything in Downloads. |
| `/remove <mod>` | Uninstall a mod |
| `/info <mod>` | Details and dependency tree |
| `/updates` | Check for updates and install them |
| `/missing` | Find and fix unmet dependencies |
| `/profiles` | Switch, create, rename, delete profiles |
| `/launch` | Launch Silksong |
| `/backup` | Snapshot your saves. `list`, `restore` |
| `/logs` | Show the BepInEx log |
| `/setup` | Configure paths, BepInEx and API keys |
| `/settings` | Everything toggleable |
| `/help` | `/help <command>` for detail |
| `/clear`, `/exit` | |

A few older names still work but are kept out of `/help` to stop it sprawling:
`/ls`, `/enable <mod>`, `/disable <mod>`, `/search <query>`, `/path`. These
matter for scripting — `/enable` and `/disable` set an absolute state, whereas
`/toggle` flips whatever is there, and a script wants the former. `/deps` maps
to `/info`, `/update` to `/updates`, `/switch` to `/profiles`.

## Dependencies

Thunderstore mods declare their dependencies, and Beastfly acts on them.

**On install**, anything missing is fetched automatically (turn that off with
*Auto-install dependencies*). Anything Beastfly can't fetch — not published on
Thunderstore — is reported with links instead of failing quietly:

```
beastfly> /add MenuOverhaul
  ✓ Installed Faaris-MenuOverhaul 2.0.0.
  ! 1 dependency not on Thunderstore - download by hand:
      ✗ SomeGuy-WeirdLib  wants 1.0.0  not on Thunderstore
          Thunderstore search: https://thunderstore.io/c/hollow-knight-silksong/?q=WeirdLib
          Nexus search: https://www.nexusmods.com/hollowknightsilksong/search/?gsearch=WeirdLib&gsearchtype=mods
```

**`/missing`** audits every installed mod at once, which is the command you
want after a batch of manual installs. It lists each gap with a link, then
offers to install the ones it can:

```
beastfly> /missing

  MenuTweak  enabled
      ✗ SFGrenade-WavLib  wants 1.1.1  on Thunderstore
          Thunderstore: https://thunderstore.io/c/hollow-knight-silksong/p/SFGrenade/WavLib/

  1 mod with unmet dependencies.
  Install 1 dependency from Thunderstore? [Y/n]
```

`/deps <mod>` does the same for one mod as a tree. `/enable` warns if the mod
you just switched on is missing something, and `/launch` warns before starting
the game. Aliases: `/fix`, `/doctor`.

## Update sources

**Thunderstore** is fully supported: search, install, dependency resolution
and updates. The whole Silksong community index is one request, cached for six
hours in `~/.beastfly/cache/`.

**Nexus Mods is version-check only, by design.** Nexus gates file downloads
behind Premium plus an `nxm://` handshake, so Beastfly will not pretend to
install from it. What it does: recognise Nexus download folder names
(`ShowDamage HealthBar-28-2-0-4-1758980847` → mod 28, v2.0.4), tell you when a
newer version exists, and hand you the page URL. Download it, then `/add` it.

### Getting a Nexus API key

Go to **[nexusmods.com/users/myaccount?tab=api](https://www.nexusmods.com/users/myaccount?tab=api)**
(your avatar → *Site Preferences* → *API Keys*).

That page lists a **key per application** — Vortex, Mod Organizer 2, and every
other app that has ever asked for access. **Those are not the one you want.**
Scroll past them to the **Personal API Key** section at the bottom, generate it
if you haven't already, and copy that single long string.

Then either paste it into Beastfly:

```
beastfly> /settings
  > 15                     # Nexus Mods API key
```

or, if you'd rather not have it on disk, set it in your environment:

```sh
export BEASTFLY_NEXUS_API_KEY="your-personal-key"
```

The environment variable wins over the config file, and `/settings` shows which
one is in use. Beastfly validates the key immediately and tells you whether the
account is Premium.

> **Treat the key like a password.** Pasting it into `/settings` writes it to
> `~/.beastfly/config.json`, which is outside this repo — but don't commit it,
> paste it into an issue, or share a config file that contains it. Revoke and
> regenerate it on that same Nexus page if it leaks. The environment-variable
> route avoids writing it to disk at all.

Without a key, Nexus mods still show up in `/ls` and `/updates` names them —
they're just skipped during version checks.

Mods installed by hand with no manifest and no Nexus-style name can't be
version-checked at all. Beastfly says so rather than guessing.

## Save backups

Silksong keeps its saves *inside the Wine prefix*
(`drive_c/users/…/AppData/LocalLow/Team Cherry/Hollow Knight Silksong`), where
nothing on the Mac side is backing them up — and a modded run is exactly the
kind that eats a save file.

So `/launch` snapshots them first, every time, labelled with the profile you're
launching:

```
  Saves backed up (9 files) → saves_2026-09-01_112723_Default.zip
```

Snapshots are zips in `~/.beastfly/backups/`, a few hundred KB each, and the
oldest are pruned past twelve. `Player.log` is skipped since it's regenerated
every run.

- `/backup` — make one now, labelled with the active profile
- `/backup list` — what you have, with sizes and ages
- `/backup restore` — pick one from a list and put it back

Restoring takes a snapshot of the current saves first, so it can't be the last
irreversible step. Turn the automatic one off under `/settings` → *Back up saves
before launching* if you'd rather do it yourself.

## Launching

With **Launch through Porting Kit** on (the default), `/launch` opens the
`.app` wrapper that contains your install — detected automatically during
`/setup`. Doorstop is already wired up inside the wrapper, so enabled mods
load. A native/Steam Mac install is launched directly instead.

`/logs` tails `BepInEx/LogOutput.log` with errors highlighted, which pairs well
with `/deps` when a mod silently fails to load.

## Platform support

Built and tested for **macOS running the Windows build through Porting Kit**
(Wineskin). That's the case the GUI managers don't cover.

Everything except launching is platform-agnostic — mod scanning, profiles,
Thunderstore, Nexus, backups all work off paths and would run anywhere Python
does. `/launch` uses `open` on the `.app` wrapper, which is macOS-only; on
Linux point the Silksong path at your Wine prefix and start the game yourself.
A native or Steam macOS install is launched directly.

Python 3.8+, standard library only.

## Development

```sh
tests/smoke.sh                 # every command against a throwaway fake install
tests/smoke.sh "/path/to/Hollow Knight Silksong"   # or against a real BepInEx tree
tests/no-secrets.sh            # refuse to commit credentials or state files
```

The smoke test builds its own game folder and `BEASTFLY_HOME` in a temp
directory, so it never touches a real install or your config. `BEASTFLY_DEBUG=1`
turns command errors into full tracebacks. Both scripts run in CI on macOS and
Linux against Python 3.8 and 3.12.

**Never commit `config.json`** — it can hold your Nexus API key. It lives in
`~/.beastfly/` and is gitignored, and `tests/no-secrets.sh` fails the build if
it or a save backup ever gets tracked.

### Releasing

Bump `VERSION` in `beastfly/ui.py`, then tag:

```sh
git tag v0.1.1 && git push origin v0.1.1
```

The release workflow checks the tag matches `VERSION`, runs both test scripts,
then publishes `.tar.gz`, `.zip` and `checksums.txt` to GitHub Releases.

## Layout

```
beastfly/
  cli.py        command loop, rendering, every command
  config.py     settings + install discovery
  mods.py       scan / install / enable / remove, BepInEx bootstrap
  profiles.py   snapshots and drift
  deps.py       dependency resolution and the /deps tree
  game.py       launching and log reading
  saves.py      save-folder snapshots
  picker.py     the arrow-key list widgets
  prompt.py     the input line and slash menu
  ui.py         colour and layout helpers
  sources/
    thunderstore.py
    nexus.py
```

State: `~/.beastfly/config.json`, `profiles.json`, `installed.json`, `cache/`.
Point `BEASTFLY_HOME` elsewhere to keep a separate setup (useful for testing).

## Licence

MIT — see `LICENSE`. Change the copyright line to your own name if you fork it.

## Credit

Feature set and layout inspired by [Cogfly](https://github.com/nix-main/Cogfly)
by Nix, the GUI Silksong manager. No code was taken from it; Beastfly is an
independent Python implementation with a different profile model.
