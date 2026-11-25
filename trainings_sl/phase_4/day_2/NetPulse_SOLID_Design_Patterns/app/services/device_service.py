"""Device use cases, independent of HTTP and storage implementations."""

from app.events import OfflineTransitionHandler
from app.models import DeviceCreate, DeviceResponse, DeviceStatus
from app.repositories.contracts import DeviceRepository


class DeviceAlreadyExistsError(Exception):
    """Raised when a device ID is already registered."""


class DeviceNotFoundError(Exception):
    """Raised when an operation references an unknown device."""


class DeviceService:
    """Apply device rules and coordinate persistence and transition events."""

    def __init__(
        self,
        device_repository: DeviceRepository,
        offline_handler: OfflineTransitionHandler,
    ) -> None:
        self._device_repository = device_repository
        self._offline_handler = offline_handler

    def register(self, device: DeviceCreate) -> DeviceResponse:
        if self._device_repository.get_device(device.device_id) is not None:
            raise DeviceAlreadyExistsError(device.device_id)
        return self._device_repository.add_device(
            DeviceResponse(**device.model_dump())
        )

    def list_devices(self) -> list[DeviceResponse]:
        return self._device_repository.list_devices()

    def get(self, device_id: str) -> DeviceResponse:
        device = self._device_repository.get_device(device_id)
        if device is None:
            raise DeviceNotFoundError(device_id)
        return device

    def update_status(
        self, device_id: str, status: DeviceStatus
    ) -> DeviceResponse:
        existing_device = self.get(device_id)
        updated_device = self._device_repository.update_status(device_id, status)
        if updated_device is None:
            raise DeviceNotFoundError(device_id)

        if existing_device.status == "online" and status == "offline":
            self._offline_handler.handle(device_id)
        return updated_device