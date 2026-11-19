from datetime import datetime, timezone

from pydantic import AwareDatetime, BaseModel, ConfigDict, FiniteFloat, field_validator

from models import Severity


class AlertCreate(BaseModel):
    title: str
    severity: Severity
    source: str
    metric_name: str
    metric_value: FiniteFloat
    threshold: FiniteFloat


class AlertOut(AlertCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: AwareDatetime

    @field_validator("created_at", mode="before")
    @classmethod
    def restore_sqlite_utc(cls, value: object) -> object:
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class ExplainResponse(BaseModel):
    alert_id: int
    explanation: str
    generated_at: AwareDatetime
