"""Portable persistence. One account row is the transaction and locking boundary."""
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import RLock
from sqlalchemy import create_engine, String, JSON, DateTime, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from sqlalchemy.pool import StaticPool

class Base(DeclarativeBase): pass
class Account(Base):
    __tablename__='accounts'
    id: Mapped[str]=mapped_column(String(40), primary_key=True)
    key_hash: Mapped[str]=mapped_column(String(64))
    state: Mapped[dict]=mapped_column(JSON)
class Record(Base):
    __tablename__='records'
    id: Mapped[str]=mapped_column(String(180), primary_key=True)
    kind: Mapped[str]=mapped_column(String(24),index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
    payload: Mapped[dict]=mapped_column(JSON)

class Store:
    def __init__(self,url):
        options={'connect_args':{'check_same_thread':False}} if url.startswith('sqlite') else {}
        if url in ('sqlite://','sqlite:///:memory:'):options['poolclass']=StaticPool
        self.engine=create_engine(url,**options);self.lock=RLock();Base.metadata.create_all(self.engine)
    @contextmanager
    def transaction(self):
        # SQLite serializes writers; PostgreSQL also locks the account row below.
        with self.lock, Session(self.engine) as session:
            try:
                if self.engine.dialect.name=='sqlite':session.execute(text('BEGIN IMMEDIATE'))
                yield session
                session.commit()
            except BaseException:session.rollback();raise
    def record(self,kind,id,payload):
        with self.transaction() as session:
            if session.get(Record,id) is None:
                session.add(Record(id=id,kind=kind,created_at=datetime.now(timezone.utc),payload=payload))
    def records(self,kind,limit=100):
        with self.lock, Session(self.engine) as session:
            return [r.payload for r in session.scalars(select(Record).where(Record.kind==kind).order_by(Record.created_at.desc()).limit(limit))]
    def close(self):self.engine.dispose()
