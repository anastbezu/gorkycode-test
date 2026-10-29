# Инфраструктура сервера

## Хост и ресурсы
- **Провайдер:** VPS в Швеции (IP: `89.169.34.105`)
- **Ресурсы:** 1 ядро (vCPU), 4 ГБ RAM, 10 ГБ NVMe
- **ОС:** Ubuntu 24.04 LTS
- **Доступ:** SSH (порт 22), вход по SSH-ключу

## Сеть и безопасность
- **Домены:** `gorky.bond` (основной) и `www.gorky.bond` (301 редирект на основной домен)
- **Фаервол (UFW):** открыты только порты 22 (SSH), 80 (HTTP), 443 (HTTPS)

## Веб-сервер и SSL
- **Nginx:** установлен непосредственно на хосте (системная служба systemd), выполняет роль reverse proxy и терминатора SSL
- **SSL-сертификат:** Let's Encrypt (Certbot), настроен авторедирект на HTTPS и автоматическое продление

## Окружение приложений
- **Контейнеризация:** Docker Engine, Docker Compose v2
- **Доступность API:** OpenAI, Anthropic, Google Gemini доступны напрямую

## Деплой приложения

### Схема
```
Интернет ──443──▶ Nginx на хосте (HTTPS, Let's Encrypt)
                    ├─ /api/*, /health, /docs, /openapi.json ─▶ 127.0.0.1:8000 ─▶ контейнер backend (uvicorn)
                    └─ /                                       ─▶ 127.0.0.1:3000 ─▶ контейнер frontend (nginx со статикой)
                  контейнер postgres (pgvector) ◀── backend по сети Docker (хост postgres:5432)
                                                    127.0.0.1:5432 — только с самого сервера
```
- Все три сервиса описаны в `docker-compose.yaml` в корне репозитория. Порты опубликованы только на `127.0.0.1`: снаружи сервера доступны лишь 80 и 443 через Nginx, база извне недоступна.
- `frontend/` — страница ассистента (React, собирается в образе при деплое), устройство — [`modules/frontend.md`](modules/frontend.md).
- Данные базы — в томе Docker `postgres_data`, переживают пересборку и перезапуск контейнеров.

### Nginx
В `server`-блоке `gorky.bond` с `listen 443 ssl` (его создал certbot):

```nginx
# Бэкенд: API, документация и проверка здоровья
location ~ ^/(api|health|docs|openapi.json) {
    client_max_body_size 5m;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

# Фронтенд: всё остальное
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```
Директива `client_max_body_size 5m;` пропускает аудиозаписи до 5 МБ в `/api/stt` с запасом под 30 секунд речи (по умолчанию у Nginx лимит 1 МБ). Заголовки `proxy_set_header` передают `Host`, `X-Real-IP`, `X-Forwarded-For` и `X-Forwarded-Proto`; бэкенд доверяет этим заголовкам, поэтому его редиректы ведут на `https://`. После правки: `sudo nginx -t && sudo systemctl reload nginx`. Порты `8000` и `3000` — значения по умолчанию `BACKEND_PORT` и `FRONTEND_PORT`; на сервере их не меняют, иначе нужно менять и Nginx.

### Проект на сервере
- Клон репозитория — `/opt/gorkycode`, ветка `develop`. Пользователь из секрета `USERNAME` — владелец каталога, состоит в группе `docker`.
- Рядом с `docker-compose.yaml` лежит `.env` (не в git, права `600`). Нужные переменные (перечень и пояснения — в `.env.example`):
  - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` — обязательны, без них compose не запустится. Пароль — длинный, из букв и цифр (подставляется в адрес подключения без экранирования).
  - `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` — серверный ключ и модель LLM по умолчанию.
  - `CORS_ORIGINS` — необязательна, пусто — адреса по умолчанию.
  - `DATABASE_URL` на сервере не нужен: адрес базы для контейнера бэкенда собирается в `docker-compose.yaml` из `POSTGRES_*`.

### GitHub Secrets
В настройках репозитория (Settings → Secrets and variables → Actions):

| Секрет | Что в нём |
|---|---|
| `HOST` | IP или домен сервера |
| `USERNAME` | пользователь на сервере, под которым идёт деплой |
| `SSH_KEY` | приватный SSH-ключ этого пользователя (ключ только для деплоя; публичная часть — в `~/.ssh/authorized_keys` на сервере) |

### Что проверяет CI
`.github/workflows/ci.yml` — на каждый PR в `develop` и `main`, на каждый push в `develop` и вручную. Три независимые задачи:
- **Backend** — Ruff и Pytest на Postgres с pgvector;
- **Frontend** — `npm ci`, Vitest и `npm run build` (`tsc -b` + Vite — та же команда, что собирает образ);
- **Docker** — сборка образов `backend` и `frontend`. В PR — без публикации: поломка Dockerfile видна до мержа. На push в `develop` образы публикуются в GHCR (`ghcr.io/anastbezu/gorkycode-test/backend` и `/frontend`) с тегом — полным хешем коммита. На сервере образы не собираются: сборке бэкенда с torch не хватает диска 10 ГБ.

Новый пуш в PR отменяет устаревшую проверку.

### Как CD обновляет стенд
`.github/workflows/deploy.yml` запускается, когда CI на push в `develop` (в том числе мерж PR) закончился **успешно**. Красный CI — деплоя нет, на стенде остаётся прошлая версия. Вручную (Actions → CD → Run workflow) выкатывается текущий `develop` без ожидания CI — например, после правки `.env` на сервере; его образы должны быть уже опубликованы CI. Деплои идут по одному. По SSH на сервере:
1. `git fetch` и перемотка `/opt/gorkycode` ровно на коммит, который проверил CI;
2. вход в GHCR токеном задачи (истекает с её окончанием), `docker pull` образов этого коммита и тег `latest` на них — его берёт `docker-compose.yaml`, поэтому ручной `docker compose up -d` на сервере поднимает выкаченную версию;
3. `docker compose up -d --no-build --remove-orphans` — контейнеры с новыми образами перезапускаются;
4. ожидание ответа `GET /health` от бэкенда и страницы от фронтенда (до 60 с) — не ответили, деплой помечается упавшим;
5. выход из GHCR и удаление неиспользуемых образов — при любом исходе, в том числе при падении: на диске 10 ГБ.

Любая ошибка останавливает скрипт, и workflow становится красным. Логи сервисов в лог Actions не выводятся (репозиторий публичный) — смотреть на сервере: `docker compose logs backend`.

### Миграции
Контейнер бэкенда при каждом старте выполняет `alembic upgrade head`, затем запускает `uvicorn main:app`. Применённые миграции пропускаются; упала миграция — сервер не стартует, `/health` не отвечает, деплой красный. Отдельного шага миграций в CD нет.
