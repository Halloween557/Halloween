"""Apply all sql/*.sql migration files to Neon in order. Uses DATABASE_URL from .env."""

from pathlib import Path

import psycopg
from psycopg import ClientCursor
from dotenv import load_dotenv

from db import database_url

load_dotenv()

SQL_DIR = Path(__file__).parent / "sql"


def main():
    url = database_url()
    sql_files = sorted(SQL_DIR.glob("*.sql"))
    if not sql_files:
        print("No SQL migration files found.")
        return

    with psycopg.connect(url, autocommit=True, cursor_factory=ClientCursor) as conn:
        for sql_file in sql_files:
            sql = sql_file.read_text(encoding="utf-8")
            conn.execute(sql)
            print(f"Applied {sql_file.name}")


if __name__ == "__main__":
    main()

