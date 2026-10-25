"""Ручная загрузка стартового датасета пользователю (для тестирования).

Из корня репозитория (как в постановке backend-01b):
    uv run --project backend python -m backend.scripts.load_dataset --user-id <UUID>
Или из папки backend/:
    uv run python -m scripts.load_dataset --user-id <UUID> [--timezone Europe/Moscow]

Без --user-id генерирует новый UUID и печатает его.
"""

import argparse
import logging
import sys
from pathlib import Path
from uuid import UUID, uuid4

# Код бэкенда импортируется как `db`, `services`, … от папки backend/ —
# добавляем её в путь, чтобы запуск работал и из корня репозитория.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from db import SessionLocal  # noqa: E402
from services.bootstrap import bootstrap_user_data  # noqa: E402

log = logging.getLogger("load_dataset")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Загрузить стартовый датасет пользователю")
    parser.add_argument("--user-id", type=UUID, default=None, help="UUID пользователя")
    parser.add_argument(
        "--timezone", default="Europe/Moscow", help="IANA-пояс пользователя (по умолчанию МСК)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    user_id = args.user_id or uuid4()
    log.info("Пользователь: %s, пояс: %s", user_id, args.timezone)
    with SessionLocal() as db:
        loaded = bootstrap_user_data(db, user_id, args.timezone)

    if loaded:
        log.info("Загружено записей: %d", loaded)
    else:
        log.info("У пользователя уже есть записи — повторный импорт пропущен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
