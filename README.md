# Английский для разработчиков

Портфолио-проект Python backend: сайт с короткими интерактивными уроками английского для разработчиков A2–B1. Первый реализуемый сценарий — подбор стартовой сложности по отмеченным незнакомым словам, без обязательной регистрации.

Реализованы API онбординга и аккаунтов, PostgreSQL-схема, миграции и неизменяемая публикация пакета из пяти текстов. Интеграционные проверки выполняются на отдельной БД через Docker/PostgreSQL. Полноценного веб-интерфейса и уроков пока нет; они относятся к следующим этапам.

## Аккаунты через API

Завершённый гостевой результат можно сохранить при регистрации. `POST /api/v1/auth/register` принимает логин, пароль и ID завершённого прохождения; запрос требует действующую гостевую cookie, CSRF-токен и разрешённый Origin. Регистрация создаёт аккаунт, связывает с ним результат и отзывает гостевую сессию атомарно. У логина формат 3–32 символа ASCII (`a-z`, `0-9`, `_`); он обрезается по краям и приводится к нижнему регистру. Пароль длиной 15–128 символов сохраняется без нормализации.

`POST /api/v1/auth/login` принимает логин и пароль и выдаёт новую auth-cookie. Вход не переносит текущий гостевой результат в аккаунт. `GET /api/v1/context` возвращает контекст активной сессии и `current_run_id` аккаунта; свой аккаунтный результат читается через `GET /api/v1/onboarding/{run_id}` и сохраняется после истечения cookie. `POST /api/v1/auth/logout` отзывает auth-сессию и удаляет её cookie; повторный запрос без активной сессии возвращает 204. Изменяющие запросы требуют Origin и CSRF согласно API-контракту.

В первой версии нет подтверждения email и восстановления пароля. Если забыть пароль, восстановить доступ к аккаунту сейчас нельзя.

## Окружение

Нужны Python 3.13 и uv 0.8.15. Версия uv совпадает с закреплённой в CI.

Из корня проекта:

```bash
uv sync --locked
uv run --locked python --version
```

uv создаёт `.venv` и устанавливает зависимости из `uv.lock`. Пакет приложения называется `english_for_developers`; имя публичного GitHub-репозитория сохраняется отдельно.

## Проверки

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src/english_for_developers
uv run --locked pytest tests/unit -q
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

GitHub Actions на push и pull request восстанавливает locked-окружение, запускает Ruff, форматирование, mypy, unit- и PostgreSQL integration-тесты под Python 3.13 на Linux. Ветка `feat/onboarding-rules` опубликована: [CI для первого шага прошёл успешно](https://github.com/MIK-EN/financial-reconciliation/actions/runs/42982220945) на коммите `1bbad06`. Этот результат относится только к первому шагу, не к новому коду хранения. Main пока не обновлён. Коммиты и push выполняются только по запросу пользователя.

Следующий шаг плана — гостевая сессия и защищённая основа API. Локальные проверки шага хранения и [GitHub Actions](https://github.com/MIK-EN/financial-reconciliation/actions/runs/43003269973) прошли. Развёртывание пока не настроено.

## Документация

- [Технический дизайн](docs/design.md)
- [Пошаговый план](docs/plan.md)
- [Тексты и методические ограничения](docs/onboarding-content.md)
- [Текущее состояние](docs/STATUS.md)
