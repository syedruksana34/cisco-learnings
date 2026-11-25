"""Device business rules, independent of HTTP and storage details."""

from app.events import create_offline_alert
from app.models import AlertResponse, DeviceCreate, DeviceResponse, DeviceStatus
from app.repositories.device_repository import InMemoryDeviceRepository


class DeviceAlreadyExistsError(Exception):
    """Raised when a device ID is already registered."""


class DeviceNotFoundError(Exception):
    """Raised when an operation references an unknown device."""


class DeviceService:
    """Apply device rules and coordinate persistence and transition events."""

    def __init__(self, repository: InMemoryDeviceRepository) -> None:
        self._repository = repository

    def register(self, device: DeviceCreate) -> DeviceResponse:
        if self._repository.get_device(device.device_id) is not None:
            raise DeviceAlreadyExistsError(device.device_id)
        return self._repository.add_device(
            DeviceResponse(**device.model_dump())
        )

    def list_devices(self) -> list[DeviceResponse]:
        return self._repository.list_devices()

    def get(self, device_id: str) -> DeviceResponse:
        device = self._repository.get_device(device_id)
        if device is None:
            raise DeviceNotFoundError(device_id)
        return device

    def update_status(
        self, device_id: str, status: DeviceStatus
    ) -> DeviceResponse:
        existing_device = self.get(device_id)
        updated_device = self._repository.update_status(device_id, status)
        if updated_device is None:
            raise DeviceNotFoundError(device_id)

        if existing_device.status == "online" and status == "offline":
            create_offline_alert(self._repository, device_id)
        return updated_device

    def list_alerts(self) -> list[AlertResponse]:
        return self._repository.list_alerts()