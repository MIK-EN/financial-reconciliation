#!/usr/bin/env bash
#
# Restore a custom-format PostgreSQL dump into a brand-new database.
#
# Restoring into production (or into any existing database) is
# intentionally unsupported: this script only ever creates a fresh target
# database and never drops, truncates or overwrites anything it did not
# create in this same run. To restore over production, an operator must
# follow the runbook manually.
#
# All commands run through $PG_EXEC (for example "docker exec -i
# projecthh-postgres-1") because the PostgreSQL tools are not installed on
# the host. The local socket inside the container is used on purpose: no -h
# and no password handling anywhere in this script.
#
set -euo pipefail
umask 077

usage() {
  cat >&2 <<'EOF'
Usage: restore.sh <dump-file> <new-database-name>

Restore a pg_dump custom-format file into a NEW, empty database. The target
database must not exist yet; this script creates it and never overwrites one.

Arguments:
  <dump-file>           readable custom-format dump
  <new-database-name>   must match ^[a-z][a-z0-9_]{0,62}$ and must not be
                        postgres, template0, template1, or PGDATABASE

Required environment:
  PGUSER       database user passed to createdb/pg_restore (-U)

Optional environment:
  PG_EXEC      command prefix for PostgreSQL tools, word-split on purpose,
               e.g. "docker exec -i projecthh-postgres-1".
               Empty/unset runs the tools locally.
  PGDATABASE   production/source database name, used only as a safety guard:
               the target may not equal it.

Output:
  The target database name is printed on stdout; all messages go to stderr.

Example:
  PGUSER=english_dev PG_EXEC="docker exec -i projecthh-postgres-1" \
    ./restore.sh /var/backups/app/app-20260101T000000Z.dump app_restore_check
EOF
}

die() {
  local code=$1
  shift
  echo "restore.sh: $*" >&2
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
    usage
    die 2 "missing arguments"
    ;;
esac

if [ "$#" -ne 2 ]; then
  usage
  die 2 "expected exactly 2 arguments, got $#"
fi

dump=$1
target=$2

[ -n "${PGUSER:-}" ] || { usage; die 2 "PGUSER is required"; }

# --- All safety checks happen before anything is created or changed. ---

if [ ! -e "$dump" ]; then
  die 1 "dump file does not exist: $dump"
fi
if [ ! -f "$dump" ] || [ ! -r "$dump" ]; then
  die 1 "dump is not a readable regular file: $dump"
fi
if ! run_pg pg_restore --list < "$dump" > /dev/null; then
  die 1 "not a readable custom-format dump: $dump"
fi

if ! [[ "$target" =~ ^[a-z][a-z0-9_]{0,62}$ ]]; then
  die 2 "invalid target database name: $target (must match ^[a-z][a-z0-9_]{0,62}\$)"
fi

case "$target" in
  postgres|template0|template1)
    die 2 "refusing to use reserved database name: $target"
    ;;
esac

if [ -n "${PGDATABASE:-}" ] && [ "$target" = "$PGDATABASE" ]; then
  die 2 "refusing to restore into PGDATABASE ($target); production restores are unsupported"
fi

# Check existence. The name was validated above, so embedding it in the
# query is safe (single quotes cannot occur in a valid target name).
existing=""
if ! existing=$(run_pg psql -U "$PGUSER" -d postgres -Atc \
    "SELECT 1 FROM pg_database WHERE datname = '$target'"); then
  die 1 "could not check whether database exists: $target"
fi
if [ -n "$existing" ]; then
  die 1 "database already exists, refusing to touch it: $target"
fi

echo "restore.sh: creating database $target" >&2
if ! run_pg createdb -U "$PGUSER" "$target"; then
  die 1 "createdb failed for $target"
fi

echo "restore.sh: restoring $dump into $target" >&2
if ! run_pg pg_restore -U "$PGUSER" -d "$target" \
    --no-owner --no-privileges --exit-on-error < "$dump"; then
  # Drop only the database created by this run; nothing else is touched.
  echo "restore.sh: restore failed; dropping newly created database $target" >&2
  run_pg dropdb -U "$PGUSER" --if-exists "$target" \
    || echo "restore.sh: WARNING: dropdb failed for $target" >&2
  die 1 "restore into $target failed"
fi

echo "restored into $target" >&2
printf '%s\n' "$target"
