"""Демо-учётки: создать недостающие из `DEMO_ACCOUNTS` или сбросить к исходному датасету.

Из папки backend/ (на сервере — в контейнере: `docker compose exec backend python -m ...`):
    uv run python -m scripts.demo_accounts                 # создать недостающие
    uv run python -m scripts.demo_accounts --reset jury    # сбросить одну
    uv run python -m scripts.demo_accounts --reset-all     # сбросить все демо-учётки

Сброс удаляет записи и разговоры учётки и загружает датасет заново; остальных не трогает.
Создание недостающих бэкенд и так делает сам при каждом старте.
"""

import argparse
import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from db import SessionLocal  # noqa: E402
from services.demo_accounts import (  # noqa: E402
    DemoAccountsError,
    demo_logins,
    ensure_demo_accounts,
    parse_demo_accounts,
    reset_demo_account,
)

log = logging.getLogger("demo_accounts")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Демо-учётки с датасетом")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--reset", metavar="LOGIN", help="сбросить демо-учётку к датасету")
    group.add_argument("--reset-all", action="store_true", help="сбросить все демо-учётки")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        with SessionLocal() as db:
            if args.reset or args.reset_all:
                logins = [args.reset] if args.reset else demo_logins(db)
                if not logins:
                    log.info("Демо-учёток в базе нет.")
                for login in logins:
                    loaded = reset_demo_account(db, login)
                    log.info("«%s» сброшена: загружено записей %d", login, loaded)
                return 0

            result = ensure_demo_accounts(db, parse_demo_accounts())
    except DemoAccountsError as exc:
        log.error("%s", exc)
        return 1

    log.info("Созданы: %s", ", ".join(result.created) or "—")
    log.info("Обновлён пароль: %s", ", ".join(result.updated_password) or "—")
    if result.skipped:
        log.warning("Пропущены (логин занят обычной учёткой): %s", ", ".join(result.skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
