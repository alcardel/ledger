import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, DateTime, Integer, JSON, event, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings

def now(): return datetime.now(timezone.utc)
def uid(): return str(uuid.uuid4())
class Base(DeclarativeBase): pass
class Record(Base):
    __tablename__ = 'records'
    id: Mapped[str] = mapped_column(String(80), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(String(100), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __mapper_args__ = {'version_id_col': version}
engine = create_engine(settings.database_url, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)

def scope(db, org_id):
    db.info['org_id'] = org_id
    if db.bind.dialect.name == 'postgresql':
        db.execute(text("SELECT set_config('app.org_id', :org, true)"), {'org': org_id})

@event.listens_for(Session, 'after_begin')
def restore_tenant(session, transaction, connection):
    if connection.dialect.name == 'postgresql' and session.info.get('org_id'):
        connection.execute(text("SELECT set_config('app.org_id', :org, true)"), {'org': session.info['org_id']})

def public_data(value):
    """Keep stored diagnostics intact, but never send database internals to browsers."""
    if isinstance(value, dict): return {k: public_data(v) for k, v in value.items()}
    if isinstance(value, list): return [public_data(v) for v in value]
    if isinstance(value, str) and any(marker in value.lower() for marker in (
        'psycopg', 'sqlalchemy', 'query-invoked autoflush', '[sql:', 'traceback (most recent call last)',
        'immutable history cannot be changed',
    )):
        return 'A system error interrupted processing. Please retry or contact your administrator. This is not a credit policy finding.'
    return value


def serialize(r):
    data=public_data(r.data)
    if r.kind=='exception' and data.get('job_id'):
        if data.get('title')=='Assess could not complete': data['title']='Assessment could not complete'
        if data.get('title')=='Extract could not complete': data['title']='Document processing could not complete'
        if data.get('status')=='resolved' and data.get('recovery_job_id'):
            data['detail']='An earlier processing attempt failed. A subsequent retry completed successfully.'
    return {'id': r.id, 'version': r.version, 'created_at': r.created_at.isoformat(), 'updated_at': r.updated_at.isoformat(), **data}
