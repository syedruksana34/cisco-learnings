from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from database import DatabaseSession
from models import Alert
from schemas import AlertCreate, AlertOut, ExplainResponse
from services.explainer import generate_explanation

router = APIRouter(prefix="/alerts", tags=["alerts"])


def get_alert_or_404(alert_id: int, db: DatabaseSession) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return alert


@router.post("/", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
def create_alert(payload: AlertCreate, db: DatabaseSession) -> AlertOut:
    alert = Alert(**payload.model_dump())
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return AlertOut.model_validate(alert)


@router.get("/", response_model=list[AlertOut])
def list_alerts(db: DatabaseSession) -> list[AlertOut]:
    alerts = db.scalars(select(Alert).order_by(Alert.id))
    return [AlertOut.model_validate(alert) for alert in alerts]


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: int, db: DatabaseSession) -> AlertOut:
    return AlertOut.model_validate(get_alert_or_404(alert_id, db))


@router.post("/{alert_id}/explain", response_model=ExplainResponse)
def explain_alert(alert_id: int, db: DatabaseSession) -> ExplainResponse:
    alert = get_alert_or_404(alert_id, db)
    return ExplainResponse(
        alert_id=alert.id,
        explanation=generate_explanation(alert),
        generated_at=datetime.now(timezone.utc),
    )
