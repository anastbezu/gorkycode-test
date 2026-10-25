# devops-02: деплой приложения и CI/CD

**Исполнитель:** Настя

## Цель
Развернуть стек приложения (`backend`, `frontend`, `postgres`) на сервере `gorky.bond`, настроить обратное проксирование Nginx и автоматизировать непрерывную интеграцию и доставку (CI/CD) через GitHub Actions с автодеплоем из ветки `develop`.

## Контекст
- **Сервер:** VPS в Швеции (`89.169.34.105`), ОС Ubuntu 24.04, домен `gorky.bond`. Базовая настройка хоста выполнена в [devops-01](devops-01-nastroyka-servera.md).
- **Схема проксирования Nginx на VPS:**
  - `https://gorky.bond/api/*` → проксируется на бэкенд (`http://127.0.0.1:8000/api/*`);
  - `https://gorky.bond/health`, `/docs` и `/openapi.json` → проксируются на бэкенд (`http://127.0.0.1:8000`);
  - `https://gorky.bond/` → отдаёт статику фронтенда (или контейнер `http://127.0.0.1:3000`);
  - Все соединения принудительно идут по HTTPS через сертификат Let's Encrypt, полученный в задаче `devops-01`.
- **Конфигурация Docker Compose и окружение (`docs/decisions.md`):**
  - В файлах `docker-compose.yaml` и `.env.example` **заменить** переменную `GEMINI_API_KEY` на универсальные переменные LLM:
    * `LLM_BASE_URL` (по умолчанию `https://generativelanguage.googleapis.com/v1beta/openai/`)
    * `LLM_API_KEY` (серверный ключ по умолчанию)
    * `LLM_MODEL` (имя модели провайдера по умолчанию)
  - В `backend/Dockerfile` использовать базовый образ Python 3.13.
- **CI/CD в GitHub Actions:**
  - **CI (`.github/workflows/ci.yml`):** Срабатывает при создании и обновлении Pull Request в ветки `develop` и `main`. Запускает проверку линтера и тестов бэкенда (`ruff check` и `pytest`).
  - **CD (`.github/workflows/deploy.yml`):** Срабатывает при пуше/мерже в ветку **`develop`** (решение техлида для быстрой валидации на стенде). По SSH подключается к серверу (секреты хранятся в GitHub Secrets: `HOST`, `USERNAME`, `SSH_KEY`), выполняет `git pull origin develop` и `docker compose up -d --build`.

## Критерии готовности
- [ ] Сервисы `backend`, `frontend` и `postgres` успешно поднимаются через `docker compose up -d` на сервере.
- [ ] Эндпоинты `https://gorky.bond/health` и `https://gorky.bond/docs` открываются в браузере по безопасному HTTPS без ошибок сертификата.
- [ ] Главная страница `https://gorky.bond/` открывает веб-интерфейс.
- [ ] База данных снаружи сервера недоступна; пароль БД задаётся только в `.env` на сервере, значения по умолчанию в `docker-compose.yaml` нет.
- [ ] В `docker-compose.yaml` и `.env.example` зафиксированы переменные `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` вместо `GEMINI_API_KEY`.
- [ ] Workflow CI на GitHub Actions успешно проверяет PR на ошибки линтинга и тестов.
- [ ] Workflow CD на GitHub Actions автоматически обновляет контейнеры на сервере при мерже PR в ветку `develop`.
- [ ] Схема деплоя и список секретов задокументированы в `docs/infra.md`.

## На усмотрение исполнителя
Оптимизация слоёв Dockerfile, организация multi-stage build для фронтенда, стратегия кэширования в GitHub Actions.
