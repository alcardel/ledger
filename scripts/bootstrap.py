"""Create a least-privilege local application role; run migrations as owner."""
import os,subprocess
from sqlalchemy import create_engine,text
owner=os.environ.get('MIGRATION_DATABASE_URL','postgresql+psycopg://workbench:workbench@localhost:55432/workbench')
engine=create_engine(owner)
with engine.begin() as c:
    if not c.scalar(text("SELECT 1 FROM pg_roles WHERE rolname='workbench_app'")):
        c.execute(text("CREATE ROLE workbench_app LOGIN PASSWORD 'local_app_password' NOSUPERUSER NOBYPASSRLS"))
    c.execute(text('GRANT CONNECT ON DATABASE workbench TO workbench_app'))
subprocess.run(['../.venv/bin/alembic','upgrade','head'],cwd='backend',env={**os.environ,'DATABASE_URL':owner},check=True)
with engine.begin() as c:
    c.execute(text('GRANT USAGE ON SCHEMA public TO workbench_app'))
    c.execute(text('GRANT SELECT, INSERT, UPDATE ON records TO workbench_app'))
print('Migrated PostgreSQL; application role has no superuser or RLS bypass privileges.')
