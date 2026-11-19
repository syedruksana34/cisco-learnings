from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

database_path = Path(__file__).with_name("college.db")
engine = create_engine(URL.create("sqlite", database=str(database_path)))
SessionLocal = sessionmaker(bind=engine)


@event.listens_for(engine, "connect")
def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
    # SQLite does not enforce foreign keys by default on new connections.
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


DatabaseSession = Annotated[Session, Depends(get_db)]
