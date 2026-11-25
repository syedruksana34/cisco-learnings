"""Application-scoped dependencies shared across API requests."""

from app.repositories.device_repository import InMemoryDeviceRepository
from app.repositories.alert_repository import InMemoryAlertRepository
from app.services.alert_service import AlertService
from app.services.device_service import DeviceService
from app.events import RepositoryOfflineTransitionHandler

_device_repository = InMemoryDeviceRepository()
_alert_repository = InMemoryAlertRepository()
_offline_handler = RepositoryOfflineTransitionHandler(_alert_repository)
_device_service = DeviceService(_device_repository, _offline_handler)
_alert_service = AlertService(_alert_repository)


def get_device_service() -> DeviceService:
    """Return the shared device service."""
    return _device_service


def get_alert_service() -> AlertService:
    """Return the shared alert query service."""
    return _alert_service