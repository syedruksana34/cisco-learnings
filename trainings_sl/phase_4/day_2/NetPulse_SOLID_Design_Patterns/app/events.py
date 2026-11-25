"""Alert handlers for device status transitions."""

from datetime import datetime, timezone
from typing import Protocol

from app.models import AlertResponse
from app.repositories.contracts import AlertRepository


class OfflineTransitionHandler(Protocol):
    """Behavior required when a device transitions to offline."""

    def handle(self, device_id: str) -> AlertResponse:
        ...


class RepositoryOfflineTransitionHandler:
    """Create and store an alert for an offline transition."""

    def __init__(self, repository: AlertRepository) -> None:
        self._repository = repository

    def handle(self, device_id: str) -> AlertResponse:
        alert = AlertResponse(
            device_id=device_id,
            message=f"Device {device_id} transitioned from online to offline.",
            timestamp=datetime.now(timezone.utc),
        )
        return self._repository.save_alert(alert)