"""Alembic environment — builds the DB URL from app settings."""

from logging.config import fileConfig
from urllib.parse import quote_plus

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from alembic import context
from app.core.config import settings
from app.models.session import Session  # noqa: F401
from app.models.thread import Thread  # noqa: F401
from app.models.user import User  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

DATABASE_URL = (
    f"postgresql://{quote_plus(settings.POSTGRES_USER)}:{quote_plus(settings.POSTGRES_PASSWORD)}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    f"?sslmode={settings.POSTGRES_SSLMODE}"
)
target_metadata = SQLModel.metadata

# LangGraph checkpointer + mem0/pgvector own these — never touch them here.
EXCLUDE_TABLES = {
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
    "checkpoints",
    "longterm_memory",
    "mem0migrations",
}


def include_object(object, name, type_, reflected, compare_to):
    """Exclude externally-managed tables from autogenerate."""
    if type_ == "table" and name in EXCLUDE_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = DATABASE_URL
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
