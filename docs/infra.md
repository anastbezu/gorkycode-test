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
- `frontend/` пока отдаёт временную статическую страницу («интерфейс в разработке»); настоящий интерфейс появится с задачей фронтенда.
- Данные базы — в томе Docker `postgres_data`, переживают пересборку и перезапуск контейнеров.

### Nginx
В `server`-блоке `gorky.bond` с `listen 443 ssl` (его создал certbot) вместо стандартного `location /` поставить:

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    include proxy_params;
}

location = /health {
    proxy_pass http://127.0.0.1:8000;
    include proxy_params;
}

location /docs {
    proxy_pass http://127.0.0.1:8000;
    include proxy_params;
}

location = /openapi.json {
    proxy_pass http://127.0.0.1:8000;
    include proxy_params;
}

location / {
    proxy_pass http://127.0.0.1:3000;
    include proxy_params;
}
```
`proxy_params` (поставляется с nginx в Ubuntu) передаёт `Host`, `X-Real-IP`, `X-Forwarded-For` и `X-Forwarded-Proto`; бэкенд доверяет этим заголовкам, поэтому его редиректы ведут на `https://`. После правки: `sudo nginx -t && sudo systemctl reload nginx`. Порты `8000` и `3000` — значения по умолчанию `BACKEND_PORT` и `FRONTEND_PORT`; на сервере их не меняют, иначе нужно менять и Nginx.

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

### Как CD обновляет стенд
`.github/workflows/deploy.yml` срабатывает на каждый push в `develop` (в том числе мерж PR). Деплои идут по одному. По SSH на сервере:
1. `git pull --ff-only origin develop` в `/opt/gorkycode`;
2. `docker compose up -d --build --remove-orphans` — пересобираются изменившиеся образы, контейнеры перезапускаются;
3. ожидание ответа `GET /health` от бэкенда (до 60 с) — не ответил, деплой помечается упавшим;
4. очистка неиспользуемых образов и кэша сборки старше 3 суток — на диске 10 ГБ.

Любая ошибка останавливает скрипт, и workflow становится красным. Логи сервисов в лог Actions не выводятся (репозиторий публичный) — смотреть на сервере: `docker compose logs backend`.

### Миграции
Контейнер бэкенда при каждом старте выполняет `alembic upgrade head`, затем запускает `uvicorn main:app`. Применённые миграции пропускаются; упала миграция — сервер не стартует, `/health` не отвечает, деплой красный. Отдельного шага миграций в CD нет.
