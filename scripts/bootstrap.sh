#!/usr/bin/env bash
# Run this script only from a reviewed Hermes Weave source checkout.
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV_DIR="${HERMES_WEAVE_VENV:-$HOME/.local/share/hermes-weave/venv}"
BIN_DIR="${HERMES_WEAVE_BIN_DIR:-$HOME/.local/bin}"

if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.10+ is required.' >&2
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo 'Git is required.' >&2
  exit 1
fi
if [[ ! -d "$HOME/.hermes" ]]; then
  echo 'Hermes home (~/.hermes) was not found. Install Hermes first.' >&2
  exit 1
fi
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit('Python 3.10+ is required')
PY

if [[ -e "$VENV_DIR" && ! -f "$VENV_DIR/bin/python" ]]; then
  echo "Refusing to reuse an unexpected virtualenv path: $VENV_DIR" >&2
  exit 1
fi
if [[ -L "$VENV_DIR" ]]; then
  echo "Refusing a symlinked virtualenv path: $VENV_DIR" >&2
  exit 1
fi
if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --no-deps "$SOURCE_DIR"
"$VENV_DIR/bin/weave" skill install
mkdir -p "$BIN_DIR"
if [[ -e "$BIN_DIR/weave" && ! -L "$BIN_DIR/weave" ]]; then
  echo "Existing command $BIN_DIR/weave not replaced; use $VENV_DIR/bin/weave" >&2
elif [[ -L "$BIN_DIR/weave" && "$(readlink "$BIN_DIR/weave")" != "$VENV_DIR/bin/weave" ]]; then
  echo "Existing weave symlink not replaced; use $VENV_DIR/bin/weave" >&2
else
  ln -sfn "$VENV_DIR/bin/weave" "$BIN_DIR/weave"
fi
"$VENV_DIR/bin/weave" doctor --json
printf '\nHermes Weave installed. Start a new Hermes session, then initialize a private data repo with: weave init --host HOST --remote GIT_URL\n'
