# Бэкенд: FastAPI + Alembic. Зависимости — строго из uv.lock, без dev-группы.

# --- Сборка окружения ---
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /bin/uv

# Байт-код компилируется при сборке (быстрее старт), Python берётся из образа, кэш uv
# в слой не попадает.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_CACHE=1

WORKDIR /app

# Сначала только описание зависимостей: слой с .venv пересобирается лишь при их изменении.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# --- Итоговый образ: без uv, только окружение и код ---
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Код принадлежит root и только читается: процесс сервера работает без прав root.
RUN useradd --system --no-create-home --uid 10001 app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY . .

USER app

EXPOSE 8000

# При старте: миграции схемы, затем сервер. Упали миграции — сервер не стартует.
# --forwarded-allow-ips: запросы приходят только от Nginx на хосте (порт открыт на 127.0.0.1),
# поэтому доверяем его X-Forwarded-Proto — редиректы FastAPI строятся с https://.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000 --forwarded-allow-ips '*'"]
