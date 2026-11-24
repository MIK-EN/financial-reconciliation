#!/usr/bin/env bash
#
# Deploy one commit on the production VPS, with a backup before checkout.
# Rollback restores the previous code and images. Database restore is manual.
#
set -euo pipefail
umask 077

die() {
  local code=$1
  shift
  echo "vps-deploy.sh: $*" >&2
  exit "$code"
}

# ISO-8601 UTC, e.g. 2026-11-24T10:00:00Z.
iso_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

log_step() {
  printf '%s deploy: %s\n' "$(iso_now)" "$1"
}

dc() {
  docker compose --env-file "$ENV_FILE" -f deploy/compose.production.yaml -f deploy/compose.vps.yaml "$@"
}

check_health() {
  local attempt
  for attempt in 1 2 3 4 5; do
    if curl -fsS -o /dev/null --max-time 10 "$DEPLOY_HEALTH_URL"; then
      return 0
    fi
    if [ "$attempt" -lt 5 ]; then
      sleep "${DEPLOY_HEALTH_DELAY:-3}" || return 1
    fi
  done
  return 1
}

rollback_step() {
  local step=$1
  shift
  log_step "rollback $step"
  "$@" >&2 || die 4 "rollback failed at $step. Manual action required. DB backup: $BACKUP_PATH"
}

rollback() {
  printf 'vps-deploy.sh: deploy failed at %s\n' "$1" >&2
  rollback_step checkout git reset --keep "$PREV"
  rollback_step build dc build
  rollback_step up dc up -d --wait --wait-timeout "$DEPLOY_WAIT_TIMEOUT"
  if [ "$CADDY_CHANGED" = yes ]; then
    rollback_step "restart caddy" dc restart caddy
  fi
  printf '%s deploy rolled back to %s\n' "$(iso_now)" "$PREV"
  printf '%s DB schema was not reverted. Backup: %s\n' "$(iso_now)" "$BACKUP_PATH"
  exit 1
}

deploy_step() {
  local step=$1
  shift
  log_step "$step"
  "$@" >&2 || rollback "$step"
}

case "$#" in
  0)
    case "${SSH_ORIGINAL_COMMAND:-}" in
      "deploy "*) SHA=${SSH_ORIGINAL_COMMAND#deploy } ;;
      *) die 2 "expected SSH command: deploy <sha>" ;;
    esac
    ;;
  1) SHA=$1 ;;
  *) die 2 "usage: vps-deploy.sh <sha>" ;;
esac
[[ "$SHA" =~ ^[0123456789abcdef]{40}$ ]] || die 2 "expected a full lowercase commit SHA"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd -- "$REPO_ROOT"

case "$PWD" in
  *" "*) die 2 "repository path contains a space: $PWD" ;;
esac

ENV_FILE="${ENV_FILE:-.env.production}"
[ -f "$ENV_FILE" ] || die 2 "env file not found: $ENV_FILE"

# Export env values for Compose and the backup wrapper.
ENV_PATH=$ENV_FILE
case "$ENV_PATH" in
  /*) ;;
  *) ENV_PATH="./$ENV_PATH" ;;
esac
set -a
# shellcheck disable=SC1090
. "$ENV_PATH" || die 2 "could not source env file: $ENV_FILE"
set +a

if command -v flock >/dev/null 2>&1; then
  exec 9>"${LOCK_DIR:-/tmp}/efd-deploy.lock" || die 2 "could not open deploy lock"
  flock -n 9 || die 3 "deploy already running"
fi

DEPLOY_REMOTE="${DEPLOY_REMOTE:-origin}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
DEPLOY_WAIT_TIMEOUT="${DEPLOY_WAIT_TIMEOUT:-300}"

tracked_status="$(git status --porcelain --untracked-files=no)" || die 2 "could not check repository status"
[ -z "$tracked_status" ] || die 2 "tracked files have local modifications"

PREV="$(git rev-parse HEAD)" || die 2 "could not resolve HEAD"
log_step fetch
git fetch --quiet "$DEPLOY_REMOTE" "$DEPLOY_BRANCH" || die 2 "could not fetch deploy branch"
if [ "$SHA" = "$PREV" ]; then
  log_step "already at $SHA"
  exit 0
fi

[ "$(git cat-file -t "$SHA")" = commit ] || die 2 "target SHA does not identify a commit"
git merge-base --is-ancestor "$SHA" "refs/remotes/$DEPLOY_REMOTE/$DEPLOY_BRANCH" ||
  die 2 "target is not reachable from $DEPLOY_REMOTE/$DEPLOY_BRANCH"
git merge-base --is-ancestor "$PREV" "$SHA" || die 2 "target is not a fast-forward from HEAD"

changed_paths="$(git diff --name-only --no-renames "$PREV" "$SHA")" || die 2 "could not list changed paths"
CADDY_CHANGED=no
case $'\n'"$changed_paths"$'\n' in
  *$'\n'deploy/Caddyfile$'\n'*) CADDY_CHANGED=yes ;;
esac
[ -f deploy/compose.vps.yaml ] || die 2 "compose file not found: deploy/compose.vps.yaml"

log_step backup
backup_output="$(./scripts/vps-job.sh backup)" || die 1 "backup failed"
case "$backup_output" in
  *" backup ok: "?*) BACKUP_PATH=${backup_output#* backup ok: } ;;
  *) die 1 "backup did not report a dump path" ;;
esac

deploy_step checkout git merge --ff-only --quiet "$SHA"
deploy_step build dc build
deploy_step migrate dc run --rm migrate
deploy_step import-content dc run --rm import-content
deploy_step up dc up -d --wait --wait-timeout "$DEPLOY_WAIT_TIMEOUT"
if [ "$CADDY_CHANGED" = yes ]; then
  deploy_step "restart caddy" dc restart caddy
fi
if [ -n "${DEPLOY_HEALTH_URL:-}" ]; then
  deploy_step "health check" check_health
fi

printf '%s deploy ok: %s\n' "$(iso_now)" "$SHA"
