# Runbook: локальный production-подобный стек

Документ описывает эксплуатацию production-подобной сборки «Английский для разработчиков» на локальной машине. Публичного хостинга нет: прокси опубликован только на `127.0.0.1`. TLS, HTTPS, домен и реальный хост — задача 10; до неё стек доступен на `localhost` с портом из `HTTP_PORT`.

Все команды выполняются из корня репозитория и предполагают файл `.env.production`.

## Состав стека

- `Dockerfile` — стадии `frontend-build` (сборка Vite), `proxy` (`nginx:1.28-alpine`) и `backend` (`python:3.13-slim`, uid/gid `10001`, один worker uvicorn, флаги `--no-access-log --proxy-headers`).
- `deploy/compose.production.yaml` — проект `english-for-developers-prod`; сервисы `postgres` (`postgres:17`, именованный том `postgres_data`), `backend`, `proxy`; one-shot сервисы `migrate`, `import-content`, `cleanup` в профиле `release` — `up` их не запускает.
- `deploy/nginx.conf` — reverse proxy, статика, лимиты и формат логов; `deploy/trusted-proxies.conf` — доверенные upstream-прокси (по умолчанию не заданы).
- `scripts/backup.sh` и `scripts/restore.sh` — резервное копирование и восстановление в новую БД.

## Переменные окружения

Шаблон production-блока — в `.env.example`. Реальный env-файл отдельный и git-ignored; пример имени — `.env.production`, он передаётся через `--env-file`.

Обязательные переменные:

- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` — база и учётная запись PostgreSQL.
- `EXPECTED_ORIGIN` — origin браузера; должен совпадать с ним. Локально при `HTTP_PORT=18080` это `http://localhost:18080`; позже, при появлении TLS, — например `https://example.invalid`.

Необязательная переменная:

- `HTTP_PORT` — порт публикации прокси, по умолчанию `8080`; публикуется только `127.0.0.1`.

Пароль попадает в `DATABASE_URL`, поэтому используйте только URL-safe символы (hex). Пропущенная обязательная переменная валит compose с сообщением вида `required variable POSTGRES_DB is missing a value`.

Проверка конфигурации:

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml config -q
```

## Порядок релиза

Порядок одинаков для первого запуска и каждого релиза. Перед миграцией снимите свежую резервную копию (раздел «Резервное копирование»): откат схемы делается восстановлением, а не `alembic downgrade`.

1. Собрать образы.

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml build
```

2. Поднять PostgreSQL.

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml up -d postgres
```

3. Применить миграции.

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml run --rm migrate
```

`migrate` выполняет `alembic upgrade head`. Если шаг упал — остановитесь: не запускайте и не перезапускайте `backend` и `proxy`. Прежние контейнеры продолжают работать на старой схеме. Исправьте причину или восстановите БД из копии.

4. Импортировать контент.

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml run --rm import-content
```

Команда выполняет `content import content/onboarding-v1.json --activate --threshold-percent 20`. Первый запуск печатает `stored onboarding-v1 and activated`, повторный — `unchanged onboarding-v1`; импорт идемпотентен.

5. Запустить backend и proxy.

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml up -d
```

Миграции никогда не выполняются из команды старта backend. Backend не масштабируется: один worker, миграции и импорт запускаются явно и не параллельно.

## Проверка образа

Проверка контента без БД (образ уже собран шагом 1):

```bash
docker run --rm english-for-developers-backend:local python -m english_for_developers.cli content validate content/onboarding-v1.json
```

Печатает `valid onboarding-v1 sha256:...`.

## Готовность и остановка

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml ps
```

`postgres` и `backend` (healthcheck — python `urllib` к `/openapi.json`), а также `proxy` (`/nginx-health`) должны быть `healthy`.

Остановка:

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml down
```

`down` сохраняет том `postgres_data`. Никогда не используйте `down -v` в production: он удаляет том с базой. Проверено: после `down` и `up -d` данные на месте — вход и сохранённый результат те же.

Backend можно перезапускать: nginx резолвит его адрес в рантайме и переживает рестарт. Пока backend остановлен, `/api/*` отдаёт `502` от nginx с HTML-телом (не JSON-формат ошибки), а статические страницы продолжают отдавать `200`.

## Логи

Backend пишет по строке на запрос в stdout:

```text
<time> request request_id=<hex> method=<M> route=<template or unmatched> status=<n> duration_ms=<n> error_code=<code or ->
```

nginx пишет строку:

```text
<iso time> <method> <status> <request_time> rid=<request id>
```

В логах nginx нет URL, IP, cookie и user agent. Проверено: grep всех логов контейнеров по синтетическому паролю, токену сессии и словам `password`/`eds_session` ничего не нашёл.

Известные ограничения логов: healthcheck backend добавляет строку каждые 10 с (`route=unmatched status=200`); error log nginx на уровне `warn` печатает строку с адресом клиента при срабатывании лимита.

## Лимиты запросов

Лимиты nginx — на клиентский IP и только для POST:

- `POST /api/v1/auth/login` и `POST /api/v1/auth/register` — общая зона `5/min` + burst `5`: первые 6 запросов проходят, затем `429` с `Retry-After: 60` и JSON `{"code":"rate_limited",...}`.
- `POST /api/v1/browser-session` и `POST /api/v1/onboarding` — общая зона `10/min` + burst `5`.
- Ответы, claim, выбор сложности и все GET не лимитируются.
- Тело больше 16 KiB — `413` с JSON `request_too_large`.

Проверено вживую: восемь логинов — шесть ответов backend, затем `429`; регистрация сразу после — `429`; десять GET `/api/v1/context` — все `200`; восемь `browser-session` — шесть `201`, затем `429`. Подделанный `X-Forwarded-For` лимит не обходит: по умолчанию он не доверенный.

По умолчанию nginx берёт TCP-адрес peer. Чтобы доверять вышестоящему прокси, добавьте строки `set_real_ip_from <addr>;` в `deploy/trusted-proxies.conf` и пересоберите образ proxy. За Docker Desktop NAT все клиенты могут иметь один адрес — тогда лимиты считаются на NAT.

TLS, HTTPS, домен и реальный хост — задача 10. Cookie `__Host-` имеют флаг `Secure`, поэтому реальная браузерная сессия требует HTTPS; для проверок через curl на localhost это не мешает.

## Очистка сессий

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml run --rm cleanup
```

Печатает, например, `cleanup completed: runs=0 steps=0 sessions=0`. Удаляет только невостребованные анонимные прохождения (и их шаги), у которых `expires_at` больше 30 дней в прошлом, затем браузерные сессии старше этого срока и без ссылок. Востребованные (аккаунтные) результаты, пользователей и контент не удаляет; повторный запуск безопасен.

Рекомендуется запускать ежедневно. Пример строки cron (не установлена):

```bash
0 4 * * * cd /path/to/repo && docker compose --env-file .env.production -f deploy/compose.production.yaml run --rm cleanup >> /var/log/efd-cleanup.log 2>&1
```

## Резервное копирование

`scripts/backup.sh` читает `PGUSER`, `PGDATABASE`, `BACKUP_DIR`, опционально `KEEP` (по умолчанию `7`) и `PG_EXEC` (префикс команд PostgreSQL). Для compose-стека:

```bash
PGUSER=english_dev PGDATABASE=english_for_developers BACKUP_DIR=/var/backups/english-for-developers PG_EXEC="docker exec -i english-for-developers-prod-postgres-1" ./scripts/backup.sh
```

Создаёт `<db>-<UTC timestamp>.dump` в custom-формате `pg_dump`, проверяет его через `pg_restore --list`, публикует атомарно с правами `600`, оставляет 7 новейших копий и печатает только путь.

Политика: ежедневная копия, хранить 7 новейших; для реального использования `BACKUP_DIR` — на другом диске или хосте, не на том же, что том БД.

Потеря данных: всё записанное после последней копии при восстановлении теряется (до ~24 ч при ежедневной копии). Более строгие RPO/RTO не обещаны. Копия не шифруется и содержит хеши паролей — защитите её.

## Проверка восстановления

Повторяемая проверка (выполнена 2026-11-18 на синтетической БД с одним аккаунтом и завершённым результатом):

1. Восстановить копию в новую (scratch) БД.

```bash
PGUSER=english_dev PGDATABASE=english_for_developers PG_EXEC="docker exec -i english-for-developers-prod-postgres-1" ./scripts/restore.sh /var/backups/english-for-developers/english_for_developers-20261118T030000Z.dump restore_check_20261118
```

`restore.sh` создаёт БД; отказывается от существующей БД, имени исходной БД (`PGDATABASE`), зарезервированных и невалидных имён; ничего не перезаписывает.

2. Сравнить число строк в `users`, `runs`, шагах с ответами и пакетах контента, версию и хеш контента (`onboarding-v1`, `f35ec091…`) и ревизию alembic (`0002_unanswered_step`) между исходной и восстановленной БД — они совпали.

3. Запустить второй backend из образа `english-for-developers-backend:local` в той же compose-сети с `-e DATABASE_URL=...` (на восстановленную БД), `-e APP_ENV=production` и `-e EXPECTED_ORIGIN=...`. Вход синтетического аккаунта прошёл (неверный пароль — `401`), а JSON сохранённого результата побайтово совпал с исходным.

4. Удалить scratch-БД.

```bash
docker exec english-for-developers-prod-postgres-1 dropdb -U english_dev restore_check_20261118
```

Повторяйте после каждого изменения схемы и не реже раза в месяц.

## Восстановление production (вручную)

Автоматического восстановления production нет, и оно не выполнялось. Порядок оператора:

1. Остановить `proxy` и `backend`.
2. Свежей копией через `restore.sh` восстановить данные в НОВОЕ имя БД; существующие БД не перезаписываются.
3. Проверить данные по чек-листу выше.
4. Указать новое имя в `POSTGRES_DB` в env-файле.
5. Запустить `backend`, затем `proxy`.
6. Старую БД хранить до подтверждения.

## Откат схемы и контента

`alembic downgrade` ревизии `0001_onboarding_storage` удаляет таблицы (потеря данных), откат `0002` — no-op. Поэтому откат плохого релиза — восстановление из копии, а не `alembic downgrade`; снимайте свежую копию непосредственно перед каждой миграцией.

Публикация новой версии контента не меняет сохранённые прохождения: контент неизменяем и версионируется.
