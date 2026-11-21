# Английский для разработчиков

Портфолио-проект Python backend: сайт с короткими интерактивными уроками английского для разработчиков A2–B1. Первый реализуемый сценарий — подбор стартовой сложности по отмеченным незнакомым словам, без обязательной регистрации.

Реализованы браузерный интерфейс полного онбординга, API аккаунтов, PostgreSQL-схема, миграции и неизменяемая публикация пакета из пяти текстов. Пользователь может без регистрации пройти подбор, изменить рекомендацию, сохранить черновик в текущей вкладке, зарегистрироваться или войти и явно перенести результат. Полного учебного курса и уроков пока нет.

## Аккаунты через API

Завершённый гостевой результат можно сохранить при регистрации. `POST /api/v1/auth/register` принимает логин, пароль и ID завершённого прохождения; запрос требует действующую гостевую cookie, CSRF-токен и разрешённый Origin. Регистрация создаёт аккаунт, связывает с ним результат и отзывает гостевую сессию атомарно. У логина формат 3–32 символа ASCII (`a-z`, `0-9`, `_`); он обрезается по краям и приводится к нижнему регистру. Пароль длиной 15–128 символов сохраняется без нормализации.

`POST /api/v1/auth/login` принимает логин и пароль и выдаёт новую auth-cookie. Вход не переносит текущий гостевой результат в аккаунт. `GET /api/v1/context` возвращает контекст активной сессии и `current_run_id` аккаунта; свой аккаунтный результат читается через `GET /api/v1/onboarding/{run_id}`. Истечение cookie не удаляет результат, но для доступа после этого нужно войти снова. `POST /api/v1/auth/logout` отзывает auth-сессию и удаляет её cookie; повторный запрос без активной сессии возвращает 204. Изменяющие запросы с активной серверной сессией требуют разрешённый Origin и соответствующий CSRF-токен. Исключение: logout без активной auth-сессии требует разрешённый Origin, но не CSRF.

В первой версии нет подтверждения email и восстановления пароля. Если забыть пароль, восстановить доступ к аккаунту сейчас нельзя.

## Окружение

Нужны Python 3.13, uv 0.8.15, Node 24.22.2 (допускаются 22.12–24.x), npm 10–11, Docker Engine и Compose v2. Версия Node рекомендована в `frontend/.nvmrc`; Python и frontend-зависимости закреплены lock-файлами.

Из корня проекта:

```bash
uv sync --locked
uv run --locked python --version
```

uv создаёт `.venv` и устанавливает зависимости из `uv.lock`. Пакет приложения называется `english_for_developers`; имя публичного GitHub-репозитория сохраняется отдельно.

После подготовки PostgreSQL и импорта контента запустите backend из корня:

```bash
EXPECTED_ORIGIN=http://127.0.0.1:5173 uv run --locked uvicorn english_for_developers.app:create_app --factory --host 127.0.0.1 --port 8000
```

В другом терминале запустите frontend:

```bash
cd frontend
npm ci
npm run dev
```

Все шаги выше (PostgreSQL, миграции, импорт контента, backend и frontend) одной командой выполняет `./dev.sh`; остановка — Ctrl+C.

Сайт будет доступен на `http://127.0.0.1:5173`; Vite проксирует `/api` на FastAPI, поэтому cookie и Origin остаются в модели одного сайта.

## Проверки

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src/english_for_developers
uv run --locked pytest tests/unit -q
cd frontend
npm run typecheck
npm run build
```

Тесты проверяют исходные тексты, 104 возможных количества неизвестных слов, все шесть маршрутов, границы порога, неверные ответы, разметку и целостность контента. Для локального форматирования: `uv run --locked ruff format .`. CI проверяет код без автоматического исправления.

## PostgreSQL, миграции и публикация контента

Для локальной базы нужны Docker Engine и Compose v2. PostgreSQL 17 закреплён одинаково в Compose и CI. Создайте локальный `.env` из примера и запустите базу:

```bash
cp .env.example .env
docker compose up -d postgres
set -a; . ./.env; set +a
```

`compose.yaml` публикует порт только на `127.0.0.1`, сохраняет данные в именованном томе и создаёт отдельную БД с суффиксом `_test`. Пароль из `.env.example` предназначен только для локальной разработки; замените его в своём `.env`.

Применить миграции и проверить их соответствие моделям:

```bash
uv run --locked alembic upgrade head
uv run --locked alembic check
```

Пакет можно проверить без подключения к БД, затем сохранить и активировать для новых прохождений:

```bash
uv run --locked python -m english_for_developers.cli content validate content/onboarding-v1.json
uv run --locked python -m english_for_developers.cli content import content/onboarding-v1.json --activate --threshold-percent 20
```

Импорт той же версии и SHA-256 безопасен; изменить опубликованную версию нельзя. Новая версия и порог применяются только к новым прохождениям. Интеграционные тесты используют только `TEST_DATABASE_URL`, требующий имя БД с суффиксом `_test`:

```bash
export DATABASE_URL="$TEST_DATABASE_URL"
uv run --locked alembic upgrade head
uv run --locked alembic check
uv run --locked pytest tests/integration -q
```

Для Playwright используйте только тестовую БД. После миграции и импорта `onboarding-v1` в `$TEST_DATABASE_URL`:

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

Pytest очищает тестовую БД, поэтому после него повторите миграцию и импорт контента перед Playwright. Playwright поднимает Uvicorn и Vite сам, ждёт готовности `/openapi.json` и отказывается стартовать, если `TEST_DATABASE_URL` не оканчивается на `_test`; аккаунты в тестах синтетические (`e2e_<время>`). Повторы тестов отключены, чтобы не маскировать падения. В CI те же шаги выполняет job `e2e` (PostgreSQL 17, `npm ci`, typecheck, build, `playwright install chromium --with-deps`; при падении выгружается HTML-отчёт). Текущий набор проверяет гостевой маршрут, черновик и reload, недоступный storage, сетевой retry, 409-восстановление, выбор сложности, регистрацию, потерю auth-cookie, logout/login, явный claim, клавиатуру и мобильный viewport.

## Production-сборка локально

Production-подобный стек собирается из `Dockerfile` и `deploy/compose.production.yaml` и публикует прокси только на `127.0.0.1`, поэтому локально TLS нет. Публичное размещение на одном VPS с Caddy и Let's Encrypt описано в [runbook, «Публичное размещение на VPS»](docs/runbook.md#публичное-размещение-на-vps) и выполнено на тестовом сервере по временному HTTPS-адресу; итоговый домен пока не подключён. Cookie `__Host-` требуют HTTPS, поэтому реальная браузерная сессия появится вместе с TLS, а проверки через curl на localhost работают.

Создайте отдельный git-ignored env-файл из production-блока `.env.example` (пример имени — `.env.production`) и задайте `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` и `EXPECTED_ORIGIN`. Пароль попадает в `DATABASE_URL`, поэтому используйте hex-символы. Необязательный `HTTP_PORT` по умолчанию `8080`. Проверка конфигурации:

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml config -q
```

Релиз: сборка, запуск PostgreSQL, миграции, импорт контента, затем backend и proxy. Миграции и импорт — отдельные one-shot команды профиля `release`, а не часть старта backend.

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml build
```

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml up -d postgres
```

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml run --rm migrate
```

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml run --rm import-content
```

```bash
docker compose --env-file .env.production -f deploy/compose.production.yaml up -d
```

Полный порядок, проверка готовности, логи, лимиты запросов, очистка сессий, резервное копирование и проверка восстановления — в [runbook](docs/runbook.md).

## Демонстрация правил

Из корня проекта можно получить рекомендацию для пользователя, которому знакомы все слова:

```bash
uv run --locked python - <<'PY'
import json
from pathlib import Path

from english_for_developers.content.validation import validate_bundle
from english_for_developers.onboarding.rules import evaluate_answer, next_transition

bundle = validate_bundle(json.loads(Path('content/onboarding-v1.json').read_text()))
text_id = 'start'
while text_id is not None:
    text = bundle.get_text(text_id)
    answer = evaluate_answer(text, 'all_known', [], threshold_percent=20)
    transition = next_transition(text.id, answer.accessible, policy=bundle.routes)
    print(text.id, answer.unknown_count, '/', answer.total_count)
    text_id = transition.next_text_id
print(transition.level, transition.reason_code)
PY
```

Ожидаемый маршрут: `start → installation → parameters → constraints`, затем `complex_texts / constraints_accessible`. Это запуск чистых правил без сохранения прохождения.

## Контент и ограничения

Пакет `content/onboarding-v1.json` содержит авторские сегменты `text`/`excluded`, словарь стабильных ID каждого текста, переходы, названия и пояснения рекомендаций. Валидатор сохраняет исходное отображение и связывает повторы слова с одним ID. Нормализация не объединяет разные грамматические формы. Непомеченные числа, код, URL и неподдерживаемую письменность отклоняем при проверке пакета.

Пакет получает SHA-256 от UTF-8 JSON с отсортированными ключами без незначащих пробелов; порядок массивов значим. Возвращаемая структура неизменяема и не разделяет изменяемые коллекции с входными данными. Запрет изменения опубликованной версии в БД и хранение старых прохождений реализуются в следующих шагах.

Неоднозначные фрагменты, похожие на вызов функции или домен, требуют явной авторской разметки; это ограниченная грамматика контента, а не распознавание произвольного английского текста. Самоотметка слов не проверяет понимание, не сертифицирует CEFR и не доказывает эффективность обучения. Порог 20% остаётся продуктовой гипотезой.

## CI и дальнейшие шаги

В `.github/workflows/ci.yml` есть job `e2e` с Playwright/Chromium — он добавлен в задаче 8, но удалённо ещё не запускался; там же Python-проверки с PostgreSQL 17. Стек выпущен на одном VPS (Caddy, Let's Encrypt) на домене `engfordevelopers.ru` (недоступность через VPN принята как ограничение); cron-резервное копирование на сервере и проверка восстановления там ещё не выполнены. Коммиты и push выполняются только по запросу пользователя.

## Документация

- [Технический дизайн](docs/design.md)
- [Пошаговый план](docs/plan.md)
- [Runbook эксплуатации](docs/runbook.md)
- [Тексты и методические ограничения](docs/onboarding-content.md)
- [Текущее состояние](docs/STATUS.md)
