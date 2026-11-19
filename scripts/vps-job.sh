#!/usr/bin/env bash
#
# Cron entry point for the production VPS.
#
#   backup   daily PostgreSQL dump via scripts/backup.sh (unchanged)
#   cleanup  daily session cleanup via the compose "cleanup" one-shot
#
# Secrets are read from the env file and never echoed; set -x is not used.
#
set -euo pipefail
umask 077

usage() {
  cat >&2 <<'EOF'
Usage: vps-job.sh backup|cleanup

  backup   dump PostgreSQL through the compose "postgres" service and
           prune old dumps (delegates to scripts/backup.sh)
  cleanup  run the compose "cleanup" service (expired session cleanup)

Environment:
  ENV_FILE    env file sourced by the wrapper (default: .env.production)
  BACKUP_DIR  dump directory for backup (default: /var/backups/english-for-developers)
  LOCK_DIR    directory for the flock file (default: /tmp)

The wrapper locks per job when flock(1) is available, so overlapping cron
runs skip instead of piling up (exit code 3).
EOF
}

die() {
  local code=$1
  shift
  echo "vps-job.sh: $*" >&2
  exit "$code"
}

# ISO-8601 UTC, e.g. 2026-11-19T03:15:00Z.
iso_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

case "${1:-}" in
  backup|cleanup)
    JOB=$1
    ;;
  "")
    usage
    die 2 "job argument is required (backup|cleanup)"
    ;;
  *)
    usage
    die 2 "unknown argument: $1"
    ;;
esac

# Repo root is the parent of this script's directory, so cron can call the
# script by absolute path from any working directory.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd -- "$REPO_ROOT"

# scripts/backup.sh word-splits PG_EXEC into argv words on purpose. That only
# works when no path involved contains a space. The VPS checkout is expected
# at a space-free path (e.g. /opt/english-for-developers); fail loudly here
# instead of letting a mangled docker command fail later.
case "$PWD" in
  *" "*) die 2 "repository path contains a space: $PWD" ;;
esac

ENV_FILE="${ENV_FILE:-.env.production}"
[ -f "$ENV_FILE" ] || die 2 "env file not found: $ENV_FILE"

# Export every value for docker compose and scripts/backup.sh. The file itself
# is never printed.
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

# deploy/compose.vps.yaml is optional (introduced separately on the VPS).
COMPOSE=(docker compose --env-file "$ENV_FILE" -f deploy/compose.production.yaml)
if [ -f deploy/compose.vps.yaml ]; then
  COMPOSE+=(-f deploy/compose.vps.yaml)
fi

# Non-blocking per-job lock where flock(1) exists. macOS has no flock, so the
# script simply continues there.
if command -v flock >/dev/null 2>&1; then
  exec 9>"${LOCK_DIR:-/tmp}/efd-$JOB.lock"
  flock -n 9 || die 3 "$JOB already running"
fi

if [ "$JOB" = backup ]; then
  [ -n "${POSTGRES_USER:-}" ] || { usage; die 2 "POSTGRES_USER is required"; }
  [ -n "${POSTGRES_DB:-}" ] || { usage; die 2 "POSTGRES_DB is required"; }
  BACKUP_DIR="${BACKUP_DIR:-/var/backups/english-for-developers}"

  # backup.sh prints the final dump path as the only line on stdout; its own
  # progress messages go to stderr. On failure the non-zero status propagates
  # through the command substitution and set -e.
  dump_path="$(env \
    PGUSER="$POSTGRES_USER" \
    PGDATABASE="$POSTGRES_DB" \
    BACKUP_DIR="$BACKUP_DIR" \
    PG_EXEC="${COMPOSE[*]} exec -T postgres" \
    ./scripts/backup.sh)"
  [ -n "$dump_path" ] || die 1 "backup.sh produced no dump path"

  printf '%s backup ok: %s\n' "$(iso_now)" "$dump_path"
else
  printf '%s cleanup start\n' "$(iso_now)"
  "${COMPOSE[@]}" run --rm cleanup
  printf '%s cleanup done\n' "$(iso_now)"
fi
