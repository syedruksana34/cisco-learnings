"""Application-scoped dependencies shared across API requests."""

from app.repositories.device_repository import InMemoryDeviceRepository
from app.services.device_service import DeviceService

_device_repository = InMemoryDeviceRepository()
_device_service = DeviceService(_device_repository)


def get_device_service() -> DeviceService:
    """Return the shared service and its in-memory repository."""
    return _device_service