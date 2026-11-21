#!/usr/bin/env bash
# Поднимает сайт локально: PostgreSQL -> миграции -> контент -> backend -> frontend.
# Запуск:  ./dev.sh        Остановка: Ctrl+C
# Сайт:    http://127.0.0.1:5173
set -euo pipefail

cd "$(dirname "$0")"

BACKEND_PORT=8000
FRONTEND_URL="http://127.0.0.1:5173"

[ -f .env ] || { echo "→ .env не найден, копирую из .env.example"; cp .env.example .env; }
set -a; . ./.env; set +a

echo "→ PostgreSQL (docker compose)"
docker info >/dev/null 2>&1 || { echo "Docker не запущен. Откройте Docker Desktop и повторите."; exit 1; }
docker compose up -d --wait postgres

echo "→ Зависимости"
uv sync --locked
[ -d frontend/node_modules ] || (cd frontend && npm ci)

echo "→ Миграции и контент"
uv run --locked alembic upgrade head
uv run --locked python -m english_for_developers.cli content import content/onboarding-v1.json --activate --threshold-percent 20

for port in "$BACKEND_PORT" 5173; do
  if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Порт $port уже занят. Остановите старый сервер (lsof -iTCP:$port -sTCP:LISTEN) и повторите."
    exit 1
  fi
done

echo "→ Backend на :$BACKEND_PORT"
EXPECTED_ORIGIN="http://127.0.0.1:5173" \
  uv run --locked uvicorn english_for_developers.app:create_app --factory \
  --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

echo "→ Frontend: $FRONTEND_URL"
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --open
