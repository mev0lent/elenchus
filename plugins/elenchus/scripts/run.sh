#!/bin/sh
# Elenchus launcher. Finds a working Python 3 (python3, python, py -3), runs the engine,
# and fails CLOSED for PreToolUse when the gate is active but the engine cannot run.
# Claude Code treats a hook that cannot launch as non-blocking, so this wrapper turns
# "no Python" and "engine crashed" into exit code 2, which does block.

EVENT="$1"
INPUT=$(cat)

if [ -n "$CLAUDE_PLUGIN_ROOT" ]; then
  HERE=$(printf '%s\n' "$CLAUDE_PLUGIN_ROOT" | sed 's#\\#/#g')/scripts
else
  D=$(printf '%s\n' "$0" | sed 's#\\#/#g')
  HERE=$(dirname "$D")
fi
SCRIPT="$HERE/elenchus.py"

probe() {
  "$@" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' </dev/null >/dev/null 2>&1
}

PY=""
if probe python3; then PY="python3"
elif probe python; then PY="python"
elif probe py -3; then PY="py -3"
fi

gate_active() {
  BASE=$(printf '%s' "${ELENCHUS_DIR:-${CLAUDE_PROJECT_DIR:-.}/.elenchus}" | sed 's#\\#/#g')
  # Conservative fallback: without Python, block if any session here is active or
  # unreadable. It cannot safely identify one session from JSON without a parser.
  for STATE in "$BASE/state.json" "$BASE"/sessions/*/state.json; do
    [ -f "$STATE" ] || continue
    if ! grep -q '"active"[[:space:]]*:[[:space:]]*false' "$STATE" 2>/dev/null; then
      return 0
    fi
  done
  return 1
}

fail() {
  echo "Elenchus: $1" >&2
  if [ "$EVENT" = "hook-pretool" ] && gate_active; then
    echo "Elenchus has an active session here. This tool call is blocked until Python and the engine work again." >&2
    exit 2
  fi
  exit 1
}

if [ -z "$PY" ]; then
  fail "no working Python 3.8+ found (tried python3, python, py -3). Install Python and put it on PATH."
fi

OUT=$(printf '%s' "$INPUT" | $PY "$SCRIPT" "$@")
RC=$?
if [ "$RC" -ne 0 ]; then
  fail "engine exited with code $RC."
fi
printf '%s' "$OUT"
