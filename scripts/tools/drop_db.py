import psycopg2
import sys
import argparse
from pathlib import Path
from urllib.parse import urlparse

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))
from app.core.config import settings


def drop_create_db(database_url: str, db_name: str):
    """Drop and recreate the given database using an admin connection.

    This function will connect to the admin database (postgres) and issue
    DROP DATABASE and CREATE DATABASE statements for `db_name`.
    """
    # psycopg2 expects a postgresql:// URL (not postgresql+asyncpg://)
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    parsed = urlparse(database_url)
    admin_db = parsed._replace(path="/postgres").geturl()

    conn = psycopg2.connect(admin_db)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {db_name}")
    print(f"Dropped database {db_name} (if it existed)")
    cur.execute(f"CREATE DATABASE {db_name}")
    print(f"Created database {db_name}")
    cur.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description='Drop and recreate the application database')
    parser.add_argument('--db', default='ispbilling', help='Database name to drop/create')
    parser.add_argument('--database-url', default=None, help='Optional database admin URL (overrides config)')
    parser.add_argument('--yes', action='store_true', help='Confirm destructive operation (required for production)')
    args = parser.parse_args()

    db_name = args.db
    database_url = args.database_url or settings.database_url

    if settings.is_production and not args.yes:
        print("WARNING: You are about to operate on a production database. Re-run with --yes to confirm.")
        sys.exit(2)

    try:
        drop_create_db(database_url, db_name)
    except Exception as e:
        print('ERROR', e)
        sys.exit(1)


if __name__ == '__main__':
    main()
