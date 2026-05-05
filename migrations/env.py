"""Alembic migration environment.

Wires the project's SQLAlchemy metadata into Alembic so that ``alembic revision
--autogenerate`` produces migrations against the live ORM models.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from cascade.config import get_settings

# Import the ORM models for side effects (registering them with the metadata).
from cascade.storage import (
    Base,
    models,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_database_url() -> str:
    """Pick the URL Alembic should use, in order of priority.

    1. ``DATABASE_URL`` environment variable — set by CI and operators
    2. ``cascade.config.Settings`` — falls back to the same env var
    3. The literal in ``alembic.ini`` — only used if nothing else is set
    """
    if env_url := os.environ.get("DATABASE_URL"):
        return env_url
    settings = get_settings()
    return settings.database_url


config.set_main_option("sqlalchemy.url", _resolve_database_url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL and not an Engine. Calls to context.execute
    here emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using a synchronous engine.

    Alembic's runtime is sync; the application's runtime is async. This split is
    intentional — migrations should not depend on application startup.
    """
    cfg_section = config.get_section(config.config_ini_section, {})
    # Strip the +psycopg async driver — Alembic uses sync psycopg.
    if "+psycopg" in cfg_section.get("sqlalchemy.url", ""):
        cfg_section["sqlalchemy.url"] = cfg_section["sqlalchemy.url"].replace("+psycopg", "")

    connectable = engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
