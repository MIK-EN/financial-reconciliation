#!/usr/bin/env bash
#
# Daily PostgreSQL backup: custom-format dump, verified, atomically
# published, then pruned to the newest $KEEP dumps for one database.
#
# All commands run through $PG_EXEC (for example "docker exec -i
# projecthh-postgres-1") because pg_dump is not installed on the host.
# The local socket inside the container is used on purpose: no -h and no
# password handling anywhere in this script.
#
set -euo pipefail
umask 077

usage() {
  cat >&2 <<'EOF'
Usage: backup.sh

Create a custom-format PostgreSQL dump and keep only the newest dumps.

Required environment:
  PGUSER       database user passed to pg_dump (-U)
  PGDATABASE   database to dump
  BACKUP_DIR   directory for dump files (created if missing; no default)

Optional environment:
  KEEP         number of newest dumps to keep (default: 7, positive integer)
  PG_EXEC      command prefix for PostgreSQL tools, word-split on purpose,
               e.g. "docker exec -i projecthh-postgres-1".
               Empty/unset runs pg_dump/pg_restore locally.

Output:
  The final dump path is printed on stdout; all messages go to stderr.

Examples:
  PGUSER=english_dev PGDATABASE=app BACKUP_DIR=/var/backups/app ./backup.sh
  PGUSER=english_dev PGDATABASE=app BACKUP_DIR=/var/backups/app \
    PG_EXEC="docker exec -i projecthh-postgres-1" ./backup.sh
EOF
}

die() {
  local code=$1
  shift
  echo "backup.sh: $*" >&2
  exit "$code"
}

# Run a PostgreSQL client command, optionally through the configured prefix.
# $PG_EXEC is intentionally unquoted so it word-splits into argv words.
run_pg() {
  if [ -n "${PG_EXEC:-}" ]; then
    # shellcheck disable=SC2086
    $PG_EXEC "$@"
  else
    "$@"
  fi
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
  "")
    ;;
  *)
    usage
    die 2 "unknown argument: $1"
    ;;
esac

[ -n "${PGUSER:-}" ] || { usage; die 2 "PGUSER is required"; }
[ -n "${PGDATABASE:-}" ] || { usage; die 2 "PGDATABASE is required"; }
[ -n "${BACKUP_DIR:-}" ] || { usage; die 2 "BACKUP_DIR is required"; }

KEEP="${KEEP:-7}"
case "$KEEP" in
  ''|*[!0-9]*) usage; die 2 "KEEP must be a positive integer (got: $KEEP)" ;;
esac
if [ "$KEEP" -le 0 ]; then
  usage
  die 2 "KEEP must be a positive integer (got: $KEEP)"
fi

mkdir -p "$BACKUP_DIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
final="$BACKUP_DIR/$PGDATABASE-$timestamp.dump"
partial="$final.partial"

# Same-second reruns must not clobber an existing dump.
if [ -e "$final" ]; then
  die 1 "refusing to overwrite existing dump: $final"
fi

echo "backup.sh: dumping $PGDATABASE to $partial" >&2

# Write to a .partial file first so a failed dump never looks like a backup.
if ! run_pg pg_dump -U "$PGUSER" -d "$PGDATABASE" \
    --format=custom --no-owner --no-privileges > "$partial"; then
  rm -f -- "$partial"
  die 1 "pg_dump failed; removed $partial"
fi

# Verify the dump before publishing it.
if [ ! -s "$partial" ]; then
  rm -f -- "$partial"
  die 1 "dump is empty; removed $partial"
fi

if ! run_pg pg_restore --list < "$partial" > /dev/null; then
  rm -f -- "$partial"
  die 1 "dump verification failed (pg_restore --list); removed $partial"
fi

# Atomic publish.
mv -- "$partial" "$final"
chmod 600 "$final"

# Prune only this database's completed dumps. Timestamps in the names sort
# lexicographically, so descending name order is newest first. find handles
# an empty directory and KEEP larger than the file count naturally.
pruned=0
kept=0
while IFS= read -r old; do
  [ -n "$old" ] || continue
  if [ "$kept" -lt "$KEEP" ]; then
    kept=$((kept + 1))
  else
    rm -f -- "$old"
    pruned=$((pruned + 1))
  fi
done < <(find "$BACKUP_DIR" -maxdepth 1 -type f -name "$PGDATABASE-*.dump" -print | LC_ALL=C sort -r)

echo "backup.sh: verified $final (kept $kept, pruned $pruned)" >&2

# The dump path is the only thing on stdout.
printf '%s\n' "$final"
