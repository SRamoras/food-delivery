"""Settings read from environment variables (and from .env when running on the host)."""

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent

# "Today", weekday, opening hours and the midnight stock reset all use Lisbon time.
LISBON = ZoneInfo("Europe/Lisbon")


class Settings(BaseSettings):
    # Real environment variables win over .env. Inside Docker there is no .env file
    # (see .dockerignore): compose passes the variables the api needs.
    # extra="ignore": the plain *_PASSWORD variables in .env are for compose.yml and
    # setup.sh, not for the app.
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    # Used by the API (required: the app does not start without them)
    database_url: str  # fd_app
    mongo_url: str  # fd_app readWrite user
    redis_url: str
    enable_naive_mode: bool = False

    # Used only by scripts (setup, migrations, report export). Optional, so the api
    # container never needs the superuser, owner or root credentials.
    postgres_superuser_url: str | None = None
    migration_database_url: str | None = None  # fd_owner, for Alembic
    readonly_database_url: str | None = None  # fd_readonly, for export_reports.py
    mongo_root_url: str | None = None


settings = Settings()
