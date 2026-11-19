from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Mapped, mapped_column

from database import Base

Severity = Literal["critical", "warning", "info"]


def utc_now_for_sqlite() -> datetime:
    # SQLite's datetime storage does not preserve timezone information.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    severity: Mapped[Severity]
    source: Mapped[str]
    metric_name: Mapped[str]
    metric_value: Mapped[float]
    threshold: Mapped[float]
    created_at: Mapped[datetime] = mapped_column(default=utc_now_for_sqlite)
