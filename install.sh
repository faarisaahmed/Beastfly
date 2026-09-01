#!/bin/sh
# Install the `beastfly` launcher onto your PATH.
set -e

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
TARGET="$BIN_DIR/beastfly"

if [ ! -d "$SRC_DIR/beastfly" ]; then
  echo "install.sh: run this from the Beastfly source folder." >&2
  exit 1
fi

python3 - <<'PY' || { echo "beastfly needs Python 3.8 or newer." >&2; exit 1; }
import sys
sys.exit(0 if sys.version_info >= (3, 8) else 1)
PY

mkdir -p "$BIN_DIR"
cat > "$TARGET" <<EOF
#!/bin/sh
# beastfly - Hollow Knight: Silksong mod manager
BEASTFLY_DIR="\${BEASTFLY_DIR:-$SRC_DIR}"
if [ ! -d "\$BEASTFLY_DIR/beastfly" ]; then
  echo "beastfly: source not found at \$BEASTFLY_DIR" >&2
  echo "          set BEASTFLY_DIR to the folder containing the beastfly/ package." >&2
  exit 1
fi
PYTHONPATH="\$BEASTFLY_DIR\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m beastfly "\$@"
EOF
chmod +x "$TARGET"

echo "Installed $TARGET"
case ":$PATH:" in
  *":$BIN_DIR:"*) echo "Run: beastfly" ;;
  *) echo "Add $BIN_DIR to your PATH, then run: beastfly" ;;
esac
