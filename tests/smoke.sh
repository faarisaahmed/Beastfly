#!/bin/sh
# Exercise every command against a throwaway copy of a BepInEx tree.
# Usage: tests/smoke.sh [/path/to/Hollow Knight Silksong]
# With no argument it builds a minimal fake install, so it works on any machine.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
export BEASTFLY_HOME="$WORK/home"
GAME="$WORK/game/Hollow Knight Silksong"
DOWNLOADS="$WORK/downloads"
BEASTFLY="python3 -c 'import sys;sys.path.insert(0,\"'$ROOT'\");from beastfly.cli import main;sys.exit(main())'"

cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

mkdir -p "$GAME/BepInEx/plugins" "$GAME/BepInEx/patchers" "$GAME/BepInEx/core" "$DOWNLOADS"
touch "$GAME/Hollow Knight Silksong.exe"
: > "$GAME/BepInEx/core/BepInEx.dll"

if [ -n "$1" ]; then
  rm -rf "$GAME/BepInEx"
  cp -R "$1/BepInEx" "$GAME/BepInEx"
else
  # A plugin, a mod spanning plugins+patchers, and a Nexus-style folder name.
  mkdir -p "$GAME/BepInEx/plugins/CanvasUtil" \
           "$GAME/BepInEx/plugins/prepatcher" "$GAME/BepInEx/patchers/prepatcher" \
           "$GAME/BepInEx/plugins/QoL/ToggleHUD-28-2-0-4-1758980847"
  : > "$GAME/BepInEx/plugins/CanvasUtil/CanvasUtil.dll"
  : > "$GAME/BepInEx/plugins/prepatcher/Plugin.dll"
  : > "$GAME/BepInEx/patchers/prepatcher/Patcher.dll"
  : > "$GAME/BepInEx/plugins/QoL/ToggleHUD-28-2-0-4-1758980847/ToggleHUD.dll"
fi

python3 - "$GAME" "$DOWNLOADS" <<'PY'
import json, sys, zipfile, os
sys.path.insert(0, os.environ.get("BEASTFLY_SRC", "."))
from beastfly.config import Config
c = Config()
c["game_path"] = sys.argv[1]
c["downloads_path"] = sys.argv[2]
c["wrapper_path"] = ""
c["backup_saves_on_launch"] = False
with zipfile.ZipFile(sys.argv[2] + "/TestMod.zip", "w") as f:
    f.writestr("manifest.json", json.dumps({
        "name": "TestMod", "namespace": "tester", "version_number": "1.0.0",
        "description": "smoke test", "dependencies": []}))
    f.writestr("plugins/TestMod.dll", b"MZ")
    f.writestr("patchers/TestModPatcher.dll", b"MZ")
PY

run() {
  printf 'n\nn\n' | eval "$BEASTFLY" "$@" > "$WORK/out.txt" 2>&1 || true
  if grep -q Traceback "$WORK/out.txt"; then
    echo "FAIL  /$*"; sed -n '1,25p' "$WORK/out.txt"; FAILED=$((FAILED+1))
  else
    printf 'ok    /%s\n' "$*"
  fi
}

FAILED=0
BEASTFLY_SRC="$ROOT"; export BEASTFLY_SRC
run toggle
run toggle canvasutil
run toggle canvasutil
run ls
run "ls --disabled"
run add
run "add TestMod"
run info TestMod
run remove TestMod
run updates
run missing
run profiles
run "profiles create Second"
run "profiles Second"
run "profiles save Second"
run "profiles rename Second Third"
run "profiles delete Third"
run backup
run "backup list"
run launch
run "logs 5"
run path
run settings
run "settings auto_update on"
run help
run "help toggle"
run bogus
run --version

echo "------------------------------"
if [ "$FAILED" -eq 0 ]; then
  echo "all checks passed"
else
  echo "$FAILED failed"; exit 1
fi
