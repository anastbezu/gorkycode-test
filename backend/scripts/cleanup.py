"""Чистка по сроку хранения (30 дней) вручную. Бэкенд и так запускает её сам: при старте
и раз в 6 часов.

Из папки backend/ (на сервере — `docker compose exec backend python -m scripts.cleanup`):
    uv run python -m scripts.cleanup
"""

import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from db import SessionLocal  # noqa: E402
from services.retention import cleanup  # noqa: E402

log = logging.getLogger("cleanup")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with SessionLocal() as db:
        result = cleanup(db)
    log.info(
        "Удалено: гостей %d, отменённых записей %d, истёкших токенов %d",
        result.guests,
        result.records,
        result.tokens,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
