"""Instance-scoped in-memory storage for alerts."""

from app.models import AlertResponse


class InMemoryAlertRepository:
    """Store alerts for the lifetime of the app process."""

    def __init__(self) -> None:
        self._alerts: list[AlertResponse] = []

    def save_alert(self, alert: AlertResponse) -> AlertResponse:
        stored_alert = alert.model_copy(deep=True)
        self._alerts.append(stored_alert)
        return stored_alert.model_copy(deep=True)

    def list_alerts(self) -> list[AlertResponse]:
        return [alert.model_copy(deep=True) for alert in self._alerts]