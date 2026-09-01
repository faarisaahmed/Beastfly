#!/bin/sh
# Fail if anything that looks like a credential is committed.
# Run before pushing; also runs in CI.
set -e
cd "$(dirname "$0")/.."

FOUND=0
report() { echo "SECRET RISK: $1"; FOUND=1; }

# Beastfly's own state files must never be tracked.
if git rev-parse --git-dir >/dev/null 2>&1; then
  for name in config.json profiles.json installed.json; do
    if git ls-files --error-unmatch "$name" >/dev/null 2>&1; then
      report "$name is tracked by git"
    fi
  done
  if git ls-files | grep -qE '(^|/)saves_.*\.zip$'; then
    report "a save backup is tracked by git"
  fi
else
  echo "(not a git repo - skipping tracked-file checks)"
fi

# A Nexus personal API key is a long base64-ish string. Flag any literal
# assignment of one, while allowing the empty default and env lookups.
HITS=$(grep -rInE 'nexus_api_key"?\]?\s*[:=]\s*"[A-Za-z0-9+/_=-]{20,}"' \
        --include='*.py' --include='*.sh' --include='*.yml' --include='*.md' . || true)
[ -n "$HITS" ] && report "hard-coded nexus_api_key value:
$HITS"

# Any other long secret-shaped literal outside docs.
HITS=$(grep -rInE '(api[_-]?key|token|secret|password)"?\s*[:=]\s*"[A-Za-z0-9+/_=-]{20,}"' \
        --include='*.py' --include='*.sh' --include='*.yml' . || true)
[ -n "$HITS" ] && report "secret-shaped literal:
$HITS"

if [ "$FOUND" -eq 0 ]; then
  echo "no secrets found"
else
  echo "----"
  echo "Fix the above before committing."
  exit 1
fi
