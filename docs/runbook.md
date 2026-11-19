# Runbook: локальный production-подобный стек

Документ описывает эксплуатацию production-подобной сборки «Английский для разработчиков» на локальной машине. Публичного хостинга пока нет: прокси опубликован только на `127.0.0.1`, поэтому локально нет ни TLS, ни домена — стек доступен на `localhost` с портом из `HTTP_PORT`. Подготовка размещения на одном VPS с Caddy и Let's Encrypt описана в разделе «Публичное размещение на VPS»; реальный сервер, домен и выпуск ещё не выполнены.

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

TLS, HTTPS, домен и реальный хост — см. раздел «Публичное размещение на VPS» (подготовлен, но не развёрнут). Cookie `__Host-` имеют флаг `Secure`, поэтому реальная браузерная сессия требует HTTPS; для проверок через curl на localhost это не мешает.

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

## Публичное размещение на VPS

Публичное размещение подготовлено, но не выполнено: реальных VPS, домена и сертификата Let's Encrypt пока нет. Раздел описывает выпуск уже проверенной локально сборки на одном сервере, где Caddy завершает TLS перед nginx. Команды рассчитаны на пользователя `deploy` и checkout в `/opt/english-for-developers`; путь без пробелов — обязательное требование `scripts/vps-job.sh`.

### Состав и стоимость

| Статья | Ориентир |
| --- | --- |
| VPS 2 vCPU / 2–4 GB (рекомендация — Hetzner Cloud) | около 4–5 EUR в месяц |
| Домен | бесплатный поддомен — 0; свой домен — дополнительно к бюджету |
| Итого | цель — не более ~7 USD в месяц |

Точные цены и наличие ресурсов проверяйте в консоли провайдера на момент заказа: цифры выше — ориентир, а не подтверждённая расценка. Бюджетный потолок пользователя — около 7 USD в месяц.

### Подготовка сервера

- Ubuntu LTS.
- Отдельный непривилегированный пользователь `deploy`.
- Вход по SSH-ключам, парольный вход отключён.
- Firewall: открыты 22, 80 и 443.
- Автоматические обновления безопасности.
- Docker Engine и Compose plugin из официального apt-репозитория Docker: следуйте официальной инструкции https://docs.docker.com/engine/install/ubuntu/ — команды здесь не приводим, чтобы они не разошлись с актуальной версией.
- Пользователь `deploy` входит в группу `docker`.

```bash
sudo adduser deploy
```

```bash
sudo usermod -aG docker deploy
```

```bash
sudo ufw allow 22
```

```bash
sudo ufw allow 80
```

```bash
sudo ufw allow 443
```

```bash
sudo ufw enable
```

```bash
sudo apt update
```

```bash
sudo apt install unattended-upgrades
```

```bash
sudo dpkg-reconfigure -plow unattended-upgrades
```

Отключите парольный вход в `/etc/ssh/sshd_config` (или drop-in-файле в `/etc/ssh/sshd_config.d/`) и проверьте конфигурацию перед перезапуском:

```bash
sudo sshd -t
```

```bash
sudo systemctl reload ssh
```

Docker публикует порты через iptables напрямую и обходит `ufw`, поэтому для внешнего доступа достаточно открыть 80 и 443 (плюс 22 для администрирования). PostgreSQL и backend не публикуются вовсе; nginx остаётся на `127.0.0.1:${HTTP_PORT:-8080}` и снаружи недоступен.

### DNS и env

Запись A домена на IPv4-адрес сервера должна существовать до первого запуска: Let's Encrypt выпустит сертификат, только когда домен указывает на этот сервер, а проверка идёт через порт 80 (нужен и 443).

Создайте checkout:

```bash
sudo mkdir -p /opt/english-for-developers
```

```bash
sudo chown deploy:deploy /opt/english-for-developers
```

```bash
sudo -u deploy git clone <git-url-репозитория> /opt/english-for-developers
```

Путь без пробелов обязателен: `scripts/vps-job.sh` отказывается работать в каталоге с пробелом.

Сгенерируйте пароль и впишите его в `.env.production`:

```bash
openssl rand -hex 32
```

```bash
sudo -u deploy tee /opt/english-for-developers/.env.production >/dev/null <<'EOF'
POSTGRES_DB=english_for_developers
POSTGRES_USER=english_dev
POSTGRES_PASSWORD=вставьте-вывод-openssl-rand-hex-32
DOMAIN=demo.example.com
EXPECTED_ORIGIN=https://demo.example.com
EOF
```

```bash
sudo chmod 600 /opt/english-for-developers/.env.production
```

Замените `demo.example.com` на свой домен. `DOMAIN` обязателен для `deploy/compose.vps.yaml`, а `EXPECTED_ORIGIN` должен быть равен `https://<DOMAIN>`.

### Выпуск

Используйте оба compose-файла: базовый и VPS-override (`deploy/compose.vps.yaml` добавляет контейнер `caddy` и монтирует `deploy/trusted-proxies.vps.conf`).

Собрать образы:

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml -f deploy/compose.vps.yaml build
```

Поднять PostgreSQL:

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml -f deploy/compose.vps.yaml up -d postgres
```

Применить миграции:

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml -f deploy/compose.vps.yaml run --rm migrate
```

Импортировать контент:

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml -f deploy/compose.vps.yaml run --rm import-content
```

Запустить backend, proxy и Caddy:

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml -f deploy/compose.vps.yaml up -d
```

Если стек уже был запущен без VPS-override, перед первым `up` с ним выполните `down`: override меняет подсеть сети `default` на `172.30.50.0/24`, и переключение работающего стека ломает сеть. Используйте именно `down`, а не `down -v`: `-v` удаляет том `postgres_data` с базой. На свежем сервере просто начните сразу с двух файлов.

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml -f deploy/compose.vps.yaml down
```

### Проверка после выпуска

Выпуск сертификата может занять около минуты. Логи Caddy:

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml -f deploy/compose.vps.yaml logs caddy
```

HTTPS:

```bash
curl -I https://demo.example.com/
```

Ожидается `HTTP/2 200` и заголовок `strict-transport-security: max-age=31536000`.

Перенаправление с HTTP:

```bash
curl -I http://demo.example.com/
```

Ожидается `308` с перенаправлением на `https://…`.

Лимит логинов: восемь попыток с разными подделанными `X-Forwarded-For` (Caddy перезаписывает заголовок реальным TCP-адресом клиента):

```bash
for ip in 1.1.1.1 2.2.2.2 3.3.3.3 4.4.4.4 5.5.5.5 6.6.6.6 7.7.7.7 8.8.8.8; do curl -s -o /dev/null -w '%{http_code}\n' -X POST https://demo.example.com/api/v1/auth/login -H "X-Forwarded-For: $ip" -H 'Origin: https://demo.example.com' -H 'Content-Type: application/json' -d '{"username":"rate_check","password":"wrong-password-123"}'; done
```

Ожидается: первые шесть ответов приходят от backend (здесь это `403`: у запроса нет cookie браузерной сессии и CSRF-токена, поэтому он отклоняется приложением — для проверки лимита код ответа backend не важен), затем `429`; подделка `X-Forwarded-For` лимит не обходит.

### Расписание

Установите файл расписания (имя без точки, владелец root, права 644):

```bash
sudo install -m 644 deploy/vps/efd.cron /etc/cron.d/english-for-developers
```

Перед установкой замените в файле `deploy` на реального пользователя размещения и `/opt/english-for-developers` на реальный путь checkout. Создайте лог и каталог копий:

```bash
sudo install -m 640 -o deploy -g adm /dev/null /var/log/efd-jobs.log
```

```bash
sudo mkdir -p /var/backups/english-for-developers
```

```bash
sudo chown deploy:deploy /var/backups/english-for-developers
```

Сначала выполните обе задачи вручную от имени `deploy`:

```bash
sudo -u deploy /opt/english-for-developers/scripts/vps-job.sh backup
```

```bash
sudo -u deploy /opt/english-for-developers/scripts/vps-job.sh cleanup
```

`backup` печатает `backup ok: <путь>` и оставляет 7 новейших дампов; `cleanup` печатает `cleanup completed: runs=… steps=… sessions=…`. Обе команды уже проверены на локальном стеке (2026-11-19).

По расписанию (время — локальное время сервера, на VPS это UTC) backup стартует в 03:15, cleanup — в 03:45: дамп снимается до удаления сессий. Фактическое срабатывание cron ещё не проверялось. На следующий день посмотрите лог:

```bash
sudo tail -n 50 /var/log/efd-jobs.log
```

### Копия вне сервера

Дамп лежит на том же диске, что и БД: при отказе диска сервера потеряются и база, и все локальные копии. Регулярно забирайте свежие дампы на свой компьютер по SSH:

```bash
rsync -avz --progress deploy@<IPv4-сервера>:/var/backups/english-for-developers/ ~/efd-backups/
```

Это не автоматизировано: запускайте команду периодически (например, раз в неделю) на своей машине. У провайдера могут быть платные snapshot-копии — их цену проверьте в консоли.

RPO честно: при ежедневном backup теряется до ~24 ч данных, записанных после последнего дампа. Пока копия не вынесена с сервера, она не защищает от отказа диска.

### Проверка восстановления на VPS

Перед тем как считать демо готовым, повторите на VPS проверку из раздела «Проверка восстановления»: восстановите свежий дамп в новую scratch-БД, сравните счётчики, версии и хеш контента, ревизию alembic, проверьте вход и сохранённый результат, затем удалите scratch-БД. В реальных условиях это ещё не выполнялось.

### Что подтверждено и что нет

Проверено локально 2026-11-19 на полном compose-стеке с `DOMAIN=localhost` (внутренний CA Caddy, без Let's Encrypt):

- HTTPS отвечает `HTTP/2 200`; присутствуют `strict-transport-security: max-age=31536000`, `cache-control: no-store`, CSP и `X-Frame-Options`.
- `http://` получает `308` с перенаправлением на `https://`.
- Восемь логинов через Caddy с разными подделанными `X-Forwarded-For`: шесть ответов backend, затем `429` — лимит не обойден.
- nginx логирует реальный TCP-peer, а не адрес Caddy и не подделанный адрес; запрос напрямую к nginx из не-Caddy контейнера с подделанным `X-Forwarded-For` атрибутируется собственному адресу отправителя.
- `scripts/vps-job.sh backup` создал проверенный custom-format дамп с правами `600` и напечатал `backup ok: <путь>`; `scripts/vps-job.sh cleanup` напечатал `cleanup completed: runs=0 steps=0 sessions=0`.

Ещё не сделано:

- Реальный VPS, реальный домен и реальный сертификат Let's Encrypt.
- `flock` на Linux.
- Фактическое срабатывание cron-расписания.
- Копия вне сервера.
- Проверка восстановления на VPS.
- Публичный запуск CI.
- Проход сайта в чистом браузере.

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
