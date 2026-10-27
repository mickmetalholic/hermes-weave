#!/usr/bin/env bash
# Hermes Weave — local, source-checkout-free installer.
# Install the Python CLI and bundled Hermes Skill, then optionally run weave init.
set -euo pipefail
umask 077

SOURCE_REPO='mickmetalholic/hermes-weave'
SOURCE_REF="${HERMES_WEAVE_REF:-main}"
WEAVE_HOME="${HERMES_WEAVE_HOME:-$HOME/.hermes-weave}"
VENV_DIR="${HERMES_WEAVE_VENV:-$WEAVE_HOME/venv}"
BIN_DIR="${HERMES_WEAVE_BIN_DIR:-$HOME/.local/bin}"
RUN_INIT=1

usage() {
  cat <<'HELP'
Install Hermes Weave CLI and the Hermes Skill without keeping a source checkout.

Usage: bash install.sh [--ref BRANCH-OR-TAG] [--no-init] [--help]

Required: Python >=3.10, Git, gh (authenticated to the private source repo),
          and an existing Hermes home (~/.hermes).

--ref       GitHub source branch/tag/commit to install (default: main)
--no-init   Install only; initialize later with "weave init" (useful for agents)

All private *data* Git repository details are requested later by "weave init".
No data repo is hardcoded by this installer.
HELP
}

error() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --ref) (($# >= 2)) || error '--ref needs a value'; SOURCE_REF="$2"; shift 2 ;;
    --no-init) RUN_INIT=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) error "Unknown argument: $1" ;;
  esac
done

# No options may be passed to gh by constructing a user-controlled option string.
[[ "$SOURCE_REF" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || error 'Invalid Git ref'
[[ "$SOURCE_REF" != *'..'* && "$SOURCE_REF" != *'//'* ]] || error 'Invalid Git ref'
command -v python3 >/dev/null 2>&1 || error 'Python 3.10+ is required'
command -v git >/dev/null 2>&1 || error 'Git is required'
command -v gh >/dev/null 2>&1 || error "GitHub CLI (gh) is required while $SOURCE_REPO is private"
command -v tar >/dev/null 2>&1 || error 'tar is required'
[[ -d "$HOME/.hermes" && ! -L "$HOME/.hermes" ]] || error 'Hermes home ~/.hermes is missing or symlinked; install Hermes first'
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit('Python >=3.10 is required')
PY

gh auth status >/dev/null 2>&1 || error 'Authenticate GitHub CLI first: gh auth login'
[[ ! -L "$WEAVE_HOME" ]] || error "Refusing symlinked Weave home: $WEAVE_HOME"
[[ ! -L "$VENV_DIR" ]] || error "Refusing symlinked virtualenv: $VENV_DIR"
[[ ! -e "$WEAVE_HOME" || -d "$WEAVE_HOME" ]] || error "Weave home is not a directory: $WEAVE_HOME"
[[ ! -e "$VENV_DIR" || -x "$VENV_DIR/bin/python" ]] || error "Unexpected virtualenv path: $VENV_DIR"
if [[ -e "$BIN_DIR/weave" && ! -L "$BIN_DIR/weave" ]] || \
   [[ -L "$BIN_DIR/weave" && "$(readlink "$BIN_DIR/weave")" != "$VENV_DIR/bin/weave" ]]; then
  error "Existing weave launcher is not ours: $BIN_DIR/weave (will not overwrite)"
fi

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT
ARCHIVE="$TEMP_DIR/package.tar.gz"
mkdir -p "$TEMP_DIR/unpacked"
printf 'Downloading %s at %s with authenticated GitHub CLI...\n' "$SOURCE_REPO" "$SOURCE_REF"
gh api -H 'Accept: application/vnd.github+json' "repos/$SOURCE_REPO/tarball/$SOURCE_REF" > "$ARCHIVE" \
  || error 'Could not download source archive (check repo access/ref)'
tar -tzf "$ARCHIVE" >/dev/null || error 'GitHub response is not a valid tar.gz archive'
tar -xzf "$ARCHIVE" -C "$TEMP_DIR/unpacked"

# GitHub archives are wrapped in exactly one top-level directory.
shopt -s nullglob dotglob
unpacked=("$TEMP_DIR/unpacked"/*)
(( ${#unpacked[@]} == 1 )) || error 'Unexpected archive layout'
PKG_DIR="${unpacked[0]}"
[[ -d "$PKG_DIR" && -f "$PKG_DIR/pyproject.toml" ]] || error 'Archive is missing Python project metadata'
[[ -f "$PKG_DIR/src/hermes_weave/resources/SKILL.md" ]] || error 'Archive is missing the bundled Hermes Skill'

mkdir -p "$WEAVE_HOME/logs"
if [[ ! -d "$VENV_DIR" ]]; then
  printf 'Creating Python environment at %s\n' "$VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi
printf 'Installing Hermes Weave CLI...\n'
"$VENV_DIR/bin/python" -m pip install --disable-pip-version-check --no-deps --force-reinstall "$PKG_DIR"
[[ -x "$VENV_DIR/bin/weave" ]] || error 'CLI installation failed'
printf 'Installing Hermes Skill...\n'
"$VENV_DIR/bin/weave" skill install || error 'Skill install blocked; inspect the existing Skill and run weave skill install --replace if you approve'
mkdir -p "$BIN_DIR"
if [[ ! -e "$BIN_DIR/weave" && ! -L "$BIN_DIR/weave" ]]; then
  ln -s "$VENV_DIR/bin/weave" "$BIN_DIR/weave"
fi
printf '\nInstalled. CLI: %s\n' "$VENV_DIR/bin/weave"
"$VENV_DIR/bin/weave" doctor --json
printf '\nIf "weave" is not in PATH, add %s to PATH or use the full CLI path.\n' "$BIN_DIR"
printf 'Start a new Hermes session to activate the installed Skill.\n'
if (( RUN_INIT )); then
  if [[ -t 0 ]]; then
    printf '\nInitialize this host now? [y/N] '
    read -r confirm || confirm=''
    if [[ "$confirm" == 'y' || "$confirm" == 'Y' || "$confirm" == 'yes' ]]; then
      "$VENV_DIR/bin/weave" init
    else
      printf 'To configure a private data repository later, run: weave init\n'
    fi
  else
    printf 'No interactive terminal detected. Run "weave init" when ready.\n'
  fi
fi
