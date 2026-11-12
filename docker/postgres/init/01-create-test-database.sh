#!/bin/sh
set -eu

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=test_db="${POSTGRES_DB}_test" \
  --set=db_user="$POSTGRES_USER" <<'SQL'
CREATE DATABASE :"test_db" OWNER :"db_user";
SQL
