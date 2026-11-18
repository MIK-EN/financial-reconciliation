#!/usr/bin/env bash
# Delegate a task brief to a cheaper model via OpenCode, in an isolated git worktree.
# Usage: scripts/delegate.sh <model-or-pattern> <brief.md> [slug]
#   model-or-pattern: full id "provider/model", or a pattern like "deepseek" / "longcat"
#                     (pattern resolves against `opencode models`, free models preferred)
# Env: DELEGATE_TIMEOUT (sec, default 1200), DELEGATE_DIR (worktrees base)
set -euo pipefail

MODEL_ARG="${1:?usage: delegate.sh <model-or-pattern> <brief.md> [slug]}"
BRIEF="$(cd "$(dirname "${2:?brief file required}")" && pwd)/$(basename "$2")"
SLUG="${3:-$(basename "$2" .md)}"
[ -f "$BRIEF" ] || { echo "brief not found: $BRIEF" >&2; exit 2; }

ROOT="$(git rev-parse --show-toplevel)"
# opencode binary: $OPENCODE_BIN, else PATH, else the CLI bundled with OpenCode.app
OC="${OPENCODE_BIN:-$(command -v opencode || true)}"
if [ -z "$OC" ]; then
  OC="$(ls -d "$HOME/Library/Application Support/ai.opencode.desktop/cli/"*/opencode-cli 2>/dev/null | sort -V | tail -1 || true)"
fi
[ -x "${OC:-}" ] || { echo "opencode not found (set OPENCODE_BIN)" >&2; exit 2; }
if [[ "$MODEL_ARG" == */* ]]; then
  MODEL="$MODEL_ARG"
else
  LIST="$("$OC" models 2>/dev/null)"
  MODEL="$(grep -i -- "$MODEL_ARG" <<<"$LIST" | grep -i free | head -1 || true)"
  [ -n "$MODEL" ] || MODEL="$(grep -i -- "$MODEL_ARG" <<<"$LIST" | head -1 || true)"
fi
[ -n "${MODEL:-}" ] || { echo "no model matches '$MODEL_ARG' (see: opencode models)" >&2; exit 2; }

STAMP="$(date +%Y%m%d-%H%M%S)"
BASE="${DELEGATE_DIR:-$ROOT/../.delegate-worktrees}"
BRANCH="delegate/${SLUG}-${STAMP}"
WT="$BASE/${SLUG}-${STAMP}"
LOG="$BASE/${SLUG}-${STAMP}.log"
mkdir -p "$BASE"
git -C "$ROOT" worktree add -q -b "$BRANCH" "$WT" HEAD
# agent config may be untracked: copy it so `--agent worker` resolves in the worktree
[ -d "$WT/.opencode" ] || cp -R "$ROOT/.opencode" "$WT/.opencode"

TO="${DELEGATE_TIMEOUT:-1200}"
T=()
if command -v timeout >/dev/null 2>&1; then T=(timeout "$TO")
elif command -v gtimeout >/dev/null 2>&1; then T=(gtimeout "$TO"); fi

RC=0
(cd "$WT" && ${T[@]+"${T[@]}"} "$OC" run -m "$MODEL" --agent worker --auto --archived \
  --title "delegate:$SLUG" -f "$BRIEF" \
  "Execute the attached task brief exactly and finish with the required report.") \
  >"$LOG" 2>&1 || RC=$?

echo "MODEL:    $MODEL"
echo "BRANCH:   $BRANCH"
echo "WORKTREE: $WT"
echo "LOG:      $LOG"
echo "EXIT:     $RC  (124 = timeout)"
echo "--- git status ---"
git -C "$WT" status --short -- . ':!.opencode'
echo "--- diff stat ---"
git -C "$WT" add -N -- . ':!.opencode' >/dev/null 2>&1 || true
git -C "$WT" diff --stat HEAD -- . ':!.opencode'
echo "--- worker report (tail of log) ---"
tail -n 25 "$LOG"
