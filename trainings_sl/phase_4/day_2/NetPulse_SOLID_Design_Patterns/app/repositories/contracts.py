"""Small storage contracts used by application services."""

from typing import Protocol

from app.models import AlertResponse, DeviceResponse, DeviceStatus


class DeviceRepository(Protocol):
    """Persistence operations required for device use cases."""

    def add_device(self, device: DeviceResponse) -> DeviceResponse:
        ...

    def list_devices(self) -> list[DeviceResponse]:
        ...

    def get_device(self, device_id: str) -> DeviceResponse | None:
        ...

    def update_status(
        self, device_id: str, status: DeviceStatus
    ) -> DeviceResponse | None:
        ...


class AlertRepository(Protocol):
    """Persistence operations required for alert use cases."""

    def save_alert(self, alert: AlertResponse) -> AlertResponse:
        ...

    def list_alerts(self) -> list[AlertResponse]:
        ...