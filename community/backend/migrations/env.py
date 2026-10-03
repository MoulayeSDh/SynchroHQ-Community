from logging.config import fileConfig

from alembic import context

from app.core.config import get_settings
from app.core.database import Base
from app.modules.authorization import models as authorization_models  # noqa: F401
from app.modules.forms import models as forms_models  # noqa: F401
from app.modules.hierarchy import models as hierarchy_models  # noqa: F401
from app.modules.identity import models as identity_models  # noqa: F401
from app.modules.organizations import models as organization_models  # noqa: F401
from app.modules.reports import models as report_models  # noqa: F401
from app.modules.sync import models as sync_models  # noqa: F401
from app.modules.territories import models as territory_models  # noqa: F401
from app.modules.users import models as user_models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().effective_database_url)
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from app.core.database import engine

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
