#!/bin/sh
# Elenchus launcher for Claude Code, Codex and Mistral Vibe. Finds a working Python 3,
# runs the engine, and fails CLOSED for the tool hook when a gate is active but the
# engine cannot run. Claude Code and Codex block on exit code 2; Vibe's strict pre_tool
# hook blocks on any non-zero exit, so there an idle project must exit 0.

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
broken_found=0
for SPEC in "python3" "python" "py -3"; do
  # No `set --` here: it would overwrite the hook name this script was called with.
  if command -v "${SPEC%% *}" >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    if probe $SPEC; then PY="$SPEC"; break; fi
    broken_found=1
  fi
done
# A broken PATH candidate (a Microsoft Store stub, a renamed interpreter) must
# not disable the gates when a working Python sits in a standard location.
# With no Python on PATH at all the launcher keeps failing closed.
if [ -z "$PY" ] && [ "$broken_found" = 1 ]; then
  for CAND in /usr/bin/python3 /usr/local/bin/python3 /usr/bin/python /usr/local/bin/python; do
    if [ -x "$CAND" ] && probe "$CAND"; then PY="$CAND"; break; fi
  done
fi

gate_active() {
  # Vibe runs hooks in the plugin directory, so the project comes from the payload's cwd.
  CWD=$(printf '%s' "$INPUT" | sed -n 's/.*"cwd"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | sed 's#\\\\#/#g')
  BASE=$(printf '%s' "${ELENCHUS_DIR:-${CLAUDE_PROJECT_DIR:-${CWD:-.}}/.elenchus}" | sed 's#\\#/#g')
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
  # Vibe (PLUGIN_ROOT without CLAUDE_PLUGIN_ROOT): a non-zero exit would deny the tool.
  if [ "$EVENT" = "hook-pretool" ] && [ -n "$PLUGIN_ROOT" ] && [ -z "$CLAUDE_PLUGIN_ROOT" ]; then
    exit 0
  fi
  exit 1
}

if [ -z "$PY" ]; then
  fail "no working Python 3.8+ found (tried python3, python, py -3 and standard install locations). Install Python and put it on PATH."
fi

OUT=$(printf '%s' "$INPUT" | $PY "$SCRIPT" "$EVENT")
RC=$?
if [ "$RC" -ne 0 ]; then
  fail "engine exited with code $RC."
fi
printf '%s' "$OUT"
