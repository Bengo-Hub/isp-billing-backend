import psycopg2
from urllib.parse import urlparse
from app.core.config import settings

if settings.database_url.startswith('postgresql+asyncpg://'):
    dburl = settings.database_url.replace('postgresql+asyncpg://', 'postgresql://')
else:
    dburl = settings.database_url

print('Connecting to:', dburl)
conn = psycopg2.connect(dburl)
cur = conn.cursor()
try:
    cur.execute("select version_num from alembic_version")
    v = cur.fetchone()
    print('alembic_version:', v)
except Exception as e:
    print('alembic_version check failed:', e)

try:
    cur.execute("select to_regclass('public.users')")
    t = cur.fetchone()
    print('users table exists:', bool(t and t[0]))
except Exception as e:
    print('users table check failed:', e)

cur.close()
conn.close()