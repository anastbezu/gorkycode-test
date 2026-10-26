"""Окружение Alembic: схема — из `db.models.Base.metadata`, адрес базы — из `DATABASE_URL`."""

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
from db.models import Base
from db.session import database_url

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: иначе fileConfig отключает уже созданные логгеры приложения
    # (агент и др.) — тесты, которые проверяют логи после миграций в conftest, молча падают.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    # Тесты могут подставить свою базу через config.set_main_option("sqlalchemy.url", ...)
    return config.get_main_option("sqlalchemy.url") or database_url()


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql` — только напечатать SQL, без подключения к базе."""
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
