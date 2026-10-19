import json
import os
from pathlib import Path
from sqlalchemy import create_engine, String, Text, Integer, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .schema import now, uid


class Base(DeclarativeBase):
    pass


class CaseRow(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class RunRow(Base):
    __tablename__ = "review_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(String(32), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default=now)


def encode(data):
    return json.dumps(data, ensure_ascii=False)


def database(url: str):
    kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def setup(conn, _):
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
    return engine, sessionmaker(engine, expire_on_commit=False)


def initialize(engine):
    Base.metadata.create_all(engine)


def case_dict(row):
    return {"id": row.id, "revision": row.revision, "created_at": row.created_at, **json.loads(row.payload)}


def run_dict(row):
    return {"id": row.id, "case_id": row.case_id, "revision": row.revision,
            "status": row.status, "created_at": row.created_at, **json.loads(row.payload)}
