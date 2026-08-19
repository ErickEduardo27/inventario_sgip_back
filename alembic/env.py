from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings
from app.db.base import Base

# Registra metadata de todas las tablas
from app.modules.campaigns import models as campaigns_models  # noqa: F401
from app.modules.catalog import models as catalog_models  # noqa: F401
from app.modules.contacts import models as contacts_models  # noqa: F401
from app.modules.iam import models as iam_models  # noqa: F401
from app.modules.inventory import geo_models as inventory_geo_models  # noqa: F401
from app.modules.inventory import attendance_models as inventory_attendance_models  # noqa: F401
from app.modules.inventory import models as inventory_models  # noqa: F401
from app.modules.omnichannel import models as omnichannel_models  # noqa: F401
from app.modules.scheduled_messages import models as scheduled_messages_models  # noqa: F401
from app.modules.segments import models as segments_models  # noqa: F401
from app.modules.settings import models as settings_models  # noqa: F401
from app.modules.surveys import models as surveys_models  # noqa: F401
from app.modules.templates import models as templates_models  # noqa: F401
from app.modules.tenants import models as tenants_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
DATABASE_URL = get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
