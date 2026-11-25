"""Alert query use cases."""

from app.models import AlertResponse
from app.repositories.contracts import AlertRepository


class AlertService:
    """Provide alert queries without depending on device storage."""

    def __init__(self, repository: AlertRepository) -> None:
        self._repository = repository

    def list_alerts(self) -> list[AlertResponse]:
        return self._repository.list_alerts()