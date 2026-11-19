from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

database_path = Path(__file__).with_name("alerts.db")
engine = create_engine(URL.create("sqlite", database=str(database_path)))
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


DatabaseSession = Annotated[Session, Depends(get_db)]
