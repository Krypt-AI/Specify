"""Apply the row-level security policies (sql/row_level_security.sql) as the schema owner.

The backend container runs this after `alembic upgrade head` on every start, so new tables are
always covered. It does nothing unless REQUEST_DATABASE_URL is set; the specify_app role in that
URL is created (or updated) with the URL's password:
  python -m app.db.rls
"""
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.engine import make_url

SCRIPT = Path(__file__).resolve().parents[2] / "sql" / "row_level_security.sql"
APP_ROLE = "specify_app"


def apply_row_level_security(engine: Engine, app_role_password: str | None = None) -> None:
    with engine.begin() as connection:
        driver = connection.connection.driver_connection
        # Executed as psql would, without parameters, so format()'s %I is not read as a placeholder.
        driver.execute(SCRIPT.read_text(encoding="utf-8"))
        if app_role_password:
            password = driver.execute("SELECT quote_literal(%s)", (app_role_password,)).fetchone()[0]
            driver.execute(f"ALTER ROLE {APP_ROLE} PASSWORD {password}")


def main() -> None:
    from app.core.config import get_settings
    from app.db.session import engine

    request_url = get_settings().request_database_url
    if not request_url:
        print("REQUEST_DATABASE_URL is not set; requests use the owner role and row-level security is off.")
        return
    url = make_url(request_url)
    if engine.dialect.name != "postgresql" or url.username != APP_ROLE:
        raise SystemExit(f"Row-level security needs PostgreSQL and REQUEST_DATABASE_URL for the {APP_ROLE} role.")
    apply_row_level_security(engine, url.password)
    print(f"Row-level security applied; requests use the {APP_ROLE} role.")


if __name__ == "__main__":
    main()
