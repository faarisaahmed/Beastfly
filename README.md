# Beastfly

[![release](https://img.shields.io/github/v/release/faarisaahmed/Beastfly?label=release)](https://github.com/faarisaahmed/Beastfly/releases/latest)
[![downloads](https://img.shields.io/github/downloads/faarisaahmed/Beastfly/total)](https://github.com/faarisaahmed/Beastfly/releases)
[![ci](https://github.com/faarisaahmed/Beastfly/actions/workflows/ci.yml/badge.svg)](https://github.com/faarisaahmed/Beastfly/actions/workflows/ci.yml)

A terminal mod manager for **Hollow Knight: Silksong** that runs wherever the
game does: **Windows, macOS and Linux**, from **Steam, GOG, Xbox or Epic**, as
the native build or as the Windows build under **Porting Kit, Whisky,
CrossOver, Wine or Proton**.

It started with the case the GUI managers don't cover — the Windows build on a
Mac, where they can't see your install — and now covers the rest of them too.

Pure Python 3, standard library only. No pip, no build step.

## Install

Beastfly needs **Python 3.8 or newer** and nothing else. Pick your platform.

### macOS and Linux

Open Terminal (on a Mac: ⌘-Space, type "Terminal", Enter) and work through
these three steps. Copy and paste each block.

**1. Check for Python:**

```sh
python3 --version
```

- Prints a version like `Python 3.12.2` → go to step 2.
- Opens a dialog offering to install developer tools (macOS) → accept it, let
  it finish, then run the command again. macOS hasn't included Python since
  version 12.3, so this is normal.
- Says `command not found` → install it: `sudo apt install python3` on Debian
  and Ubuntu, `sudo dnf install python3` on Fedora, or from
  [python.org/downloads](https://www.python.org/downloads/) on a Mac. The
  standard installer is all you need; there is nothing to configure.

**2. Download and install.** Beastfly runs from the folder you unpack it into,
so pick somewhere permanent — not `~/Downloads`, which people tend to clear
out. These lines use a `beastfly` folder in your home directory:

```sh
mkdir -p ~/beastfly && cd ~/beastfly
curl -fsSL https://github.com/faarisaahmed/Beastfly/releases/latest/download/beastfly.tar.gz | tar xz
cd beastfly-*
./install.sh
```

**3. Run it:**

```sh
beastfly
```

Prefer a clone? Same thing, and `git pull && ./install.sh` updates it:

```sh
git clone https://github.com/faarisaahmed/Beastfly.git ~/beastfly
cd ~/beastfly && ./install.sh
```

### Windows

Open **PowerShell** (Start, type "PowerShell", Enter).

**1. Check for Python:**

```powershell
python --version
```

If that opens the Microsoft Store or says it isn't recognised, install Python
from [python.org/downloads](https://www.python.org/downloads/) and **tick "Add
python.exe to PATH"** on the first screen of the installer. Then close
PowerShell and open it again.

**2. Download and install:**

```powershell
mkdir "$env:USERPROFILE\beastfly"; cd "$env:USERPROFILE\beastfly"
curl.exe -fsSLo beastfly.zip https://github.com/faarisaahmed/Beastfly/releases/latest/download/beastfly.zip
Expand-Archive -Force beastfly.zip -DestinationPath .
cd beastfly-*
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

`install.ps1` writes one file — `beastfly.cmd` in
`%LOCALAPPDATA%\Programs\beastfly` — and adds that folder to your user PATH.

**3. Open a new terminal** (so the PATH change takes effect) **and run it:**

```powershell
beastfly
```

### First run

The first run finds your Silksong install, then offers to install **BepInEx** —
the loader that actually runs mods, without which nothing loads. Press `y` and
it downloads the current version and puts it beside the game executable for
you. Any mods you already have are adopted as they are.

That's it. From there: `/add` installs mods, `/toggle` turns them on and off,
`/launch` starts the game.

### If something goes wrong

**`beastfly: command not found`** — `install.sh` put the launcher in
`~/.local/bin`, which isn't on your `PATH`. Add it and reopen Terminal:

```sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

**`beastfly: source not found at …`** — you moved or deleted the folder you
installed from. The launcher is a pointer, not a copy. Point it at the new
location:

```sh
cd /wherever/beastfly/lives && ./install.sh
```

**Mods are installed and enabled, but the game plays vanilla.** This one fails
silently, so check `/logs` first. A log with your mods listed in it means they
loaded and the mod itself is the problem. `No BepInEx log yet` after actually
playing means BepInEx never ran, and why depends on how you play:

- **Windows build under Wine** (Porting Kit, Whisky, CrossOver, Proton) — the
  loader needs `winhttp` treated as a native library, which not every wrapper
  does by default. Open the wrapper's Wine configuration (`winecfg` →
  *Libraries*), add `winhttp`, and set it to *native, builtin*. Launching the
  game outside the wrapper won't load mods either — leave *Launch through
  Wine wrapper* on in `/settings`.
- **Native macOS or Linux build** — the loader has to be started *in front of*
  the game, by `run_bepinex.sh` rather than the executable. `/launch` does that
  for you. Starting the game from Steam or your desktop does not, unless you
  paste the launch options `/path` prints into Steam → *Properties* →
  *Launch Options*.
- **Native Windows build** — nothing extra is needed; if there's still no log,
  check that `winhttp.dll` and `doorstop_config.ini` sit next to the exe, which
  `/path` will tell you.

`install.sh` writes one file, `~/.local/bin/beastfly`, and nothing else
(`install.ps1` writes one `beastfly.cmd` and a PATH entry). All state lives in
`~/.beastfly/`, so the only thing Beastfly ever puts in your game folder is
mods.

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
  > 17                     # Nexus Mods API key
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

## Finding your install

`/setup` searches everywhere the game plausibly is on this machine and shows
you what it found, rather than making you type a path. It knows about:

| | |
| --- | --- |
| **Steam** | every library on every drive, read out of `libraryfolders.vdf` — including the one you moved to `D:` |
| **GOG** | `C:\GOG Games`, GOG Galaxy's own folder, `~/GOG Games` on Linux |
| **Xbox / Game Pass** | `XboxGames\…\Content`, which nests the real files a level deeper |
| **Epic** | `Program Files\Epic Games` |
| **macOS wrappers** | Porting Kit and Wineskin `.app` bundles, CrossOver bottles, Whisky bottles |
| **Linux prefixes** | Proton (`steamapps/compatdata`), Lutris, Heroic, Bottles, and a bare `~/.wine` |

It also works out *which build* it found — Windows, macOS or Linux — because
that decides how the game has to be started and where its saves are. A Windows
build on a Mac is the original case Beastfly was written for; a Windows build
on Linux is the same problem with Proton in place of Porting Kit.

**BepInEx is searched for separately**, because it isn't always next to the
exe:

- next to the game (the normal case)
- under `Content/`, which is how Xbox installs nest things
- one level up from the exe
- anywhere else inside the same Wine prefix
- inside another manager's profile folder (r2modman, Thunderstore Mod Manager,
  Cogfly), which keep a separate BepInEx tree per profile

If it turns one up somewhere unexpected, you're offered it with a note about
where it came from. If there's genuinely none, you get a `y/n` to install the
current Thunderstore BepInEx pack into the game folder, and failing that
`/setup` asks for a path. So a non-standard layout should not mean typing paths
by hand — and if it does for you, that's a bug worth
[reporting](https://github.com/faarisaahmed/Beastfly/issues).

That offer isn't buried in `/setup`: any time Beastfly notices the loader is
missing — at startup, or on the first command you run — it says so and asks,
once per session. Answering no leaves everything untouched.

You can always override both paths in `/settings`.

## Save backups

Silksong hides its saves somewhere different on every platform, and a modded
run is exactly the kind that eats a save file. Beastfly works out which folder
belongs to the install you configured:

| Where you play | Save folder |
| --- | --- |
| Windows | `%USERPROFILE%\AppData\LocalLow\Team Cherry\Hollow Knight Silksong` |
| macOS (native) | `~/Library/Application Support/unity.Team Cherry.Hollow Knight Silksong` |
| Linux (native) | `~/.config/unity3d/Team Cherry/Hollow Knight Silksong` |
| Wine / Porting Kit | `drive_c/users/…/AppData/LocalLow/Team Cherry/Hollow Knight Silksong` |
| Proton | `steamapps/compatdata/1030300/pfx/drive_c/users/steamuser/…` |

The last two are the ones nothing else backs up. `/path` shows which one you
got.

So `/launch` snapshots them first, every time, labelled with the profile you're
launching:

```
  Saves backed up (9 files) → saves_2026-09-01_112723_Default.zip
```

`/backup` on its own lets you pick which slots to take, newest first, so you
can grab just the run you care about:

```
Back up which saves?  ·  newest first

  ❯ [✓] user1.dat                            287 KB · 3 files · 19h ago
    [✓] user.dat                             190 KB · 3 files · 11d ago
    [✓] Settings and mod data                3 files
```

A slot travels with its shadow files — Silksong keeps a `.bak1` and a
version-stamped copy alongside each `userN.dat`, and they're backed up
together.

- `/backup` — choose slots
- `/backup all` — the whole save folder
- `/backup list` — what you have, with sizes and ages
- `/backup restore` — put one back **(experimental, see below)**

Snapshots are zips in `~/.beastfly/backups/`, a few hundred KB each, oldest
pruned past twelve. `Player.log` is skipped. Turn the automatic one off under
`/settings` → *Back up saves before launching*.

### Restoring is experimental

**Treat `/backup restore` as a last resort, not a safety net you rely on.**

All it does is copy the backed-up bytes back over your save folder. It does
*not* understand Silksong's own integrity checks, its `.bak1` shadow files, or
its version-stamped copies, and a game update between backup and restore makes
it less likely to work. It may not give you back the run you expect.

What it does get right: it snapshots your current saves *before* overwriting
them, so restoring is itself undoable — if the result looks wrong,
`/backup restore` the `before-restore` snapshot to get back where you were.
Close the game first; it will rewrite saves on exit otherwise.

The backup half is the reliable half. If a save really matters, keep a copy
somewhere outside `~/.beastfly` too.

## Launching

Getting the mod loader in front of the game is the one job that changes
completely from platform to platform, so `/launch` picks a route from what it
found during `/setup`:

| Install | What `/launch` does |
| --- | --- |
| Windows build, on Windows | Runs the exe. Windows loads `winhttp.dll` itself, so mods come along. |
| Windows build, in a macOS wrapper | Opens the `.app`, exactly like double-clicking it. Doorstop is wired up inside. |
| Windows build, on Linux | Runs it under `wine` with `WINEPREFIX` pointed at the prefix it lives in. |
| macOS or Linux build | Runs `run_bepinex.sh`, which is the **only** way mods load on those builds. |
| Steam copy | Hands it to Steam, if you turn on *Launch through Steam*. |

That fourth row is the one that catches people out. The native macOS and Linux
builds have no `winhttp.dll` equivalent to hijack, so BepInEx ships a launcher
script that sets `DYLD_INSERT_LIBRARIES` / `LD_PRELOAD` and then starts the
game. Start the executable any other way — from Steam, from your desktop — and
it boots vanilla with no error to explain why. Beastfly makes the script
executable when it installs BepInEx (the zip doesn't preserve that bit), uses
it for `/launch`, and prints the Steam launch options you need if you'd rather
start from Steam:

```
beastfly> /path
  Playing from Steam? Library → Silksong → Properties → Launch Options:
      "/…/Hollow Knight Silksong/run_bepinex.sh" %command%
```

Both routes are optional and both are in `/settings`: *Launch through Wine
wrapper* and *Launch through Steam*.

`/logs` tails `BepInEx/LogOutput.log` with errors highlighted, which pairs well
with `/deps` when a mod silently fails to load.

## Platform support

| | Finds the install | Manages mods | Launches |
| --- | --- | --- | --- |
| **Windows** — Steam, GOG, Xbox, Epic | yes | yes | yes |
| **macOS** — native build, Steam or GOG | yes | yes | yes, via `run_bepinex.sh` |
| **macOS** — Windows build in Porting Kit, Whisky, CrossOver | yes | yes | yes, opens the wrapper |
| **Linux** — native build, Steam or GOG | yes | yes | yes, via `run_bepinex.sh` |
| **Linux** — Windows build under Proton, Lutris, Heroic, Bottles | yes | yes | via `wine` or Steam |

Everything that isn't launching — scanning, profiles, Thunderstore, Nexus,
dependency resolution, backups — works off paths and behaves the same
everywhere.

The terminal interface works everywhere too. On Windows, the arrow-key lists
and the slash menu read keystrokes through `msvcrt` instead of a POSIX tty, and
the console is switched to UTF-8 and ANSI colour on startup; if any of that
isn't available, everything falls back to plain line input rather than
breaking.

The one thing Beastfly can't do for you is set Steam's launch options — Steam
has no API for it, so `/path` prints the line to paste.

Python 3.8+, standard library only.

## Development

```sh
python3 tests/platforms.py     # discovery, saves and launching, for every platform
tests/smoke.sh                 # every command against a throwaway fake install
tests/smoke.sh "/path/to/Hollow Knight Silksong"   # or against a real BepInEx tree
tests/no-secrets.sh            # refuse to commit credentials or state files
```

```powershell
python tests\platforms.py      # the same, on Windows
powershell -ExecutionPolicy Bypass -File tests\smoke.ps1
```

`tests/platforms.py` is the one that matters for portability. Any given machine
is only ever one platform, so it builds fake Steam libraries, Xbox folders,
Wine prefixes and Proton prefixes on disk, tells `platforms` it is running
somewhere else, and checks what comes back — including which command `/launch`
would have run. That means the Windows and Linux paths are covered from a Mac,
and vice versa.

The smoke tests build their own game folder and `BEASTFLY_HOME` in a temp
directory, so they never touch a real install or your config. `BEASTFLY_DEBUG=1`
turns command errors into full tracebacks. Everything runs in CI on macOS,
Linux and Windows against Python 3.8 and 3.12.

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
  platforms.py  per-OS paths, stores, prefixes and process launching
  config.py     settings + install discovery
  mods.py       scan / install / enable / remove, BepInEx bootstrap
  profiles.py   snapshots and drift
  deps.py       dependency resolution and the /deps tree
  game.py       launching and log reading
  saves.py      save-folder snapshots
  picker.py     the arrow-key list widgets
  prompt.py     the input line and slash menu
  keys.py       raw keystrokes, over termios or msvcrt
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
