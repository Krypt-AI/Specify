"""Apply the row-level security policies (sql/row_level_security.sql) as the schema owner.

Run after every `alembic upgrade head` when REQUEST_DATABASE_URL is used:
  python -m app.db.rls [--password <password for specify_app>]
"""
import argparse
from pathlib import Path

from sqlalchemy import Engine

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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--password", help=f"set the password of the {APP_ROLE} role")
    args = parser.parse_args()

    from app.db.session import engine

    if engine.dialect.name != "postgresql":
        raise SystemExit("Row-level security needs PostgreSQL.")
    apply_row_level_security(engine, args.password)
    print(f"Row-level security applied; requests may now use the {APP_ROLE} role.")


if __name__ == "__main__":
    main()
