from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.events import (
    OfflineTransitionHandler,
    RepositoryOfflineTransitionHandler,
)
from app.models import AlertResponse, DeviceCreate, DeviceResponse, DeviceStatus
from app.repositories.alert_repository import InMemoryAlertRepository
from app.repositories.contracts import DeviceRepository
from app.repositories.device_repository import InMemoryDeviceRepository
from app.services.device_service import (
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    DeviceService,
)


class DictionaryDeviceRepository:
    """Alternative DeviceRepository implementation for substitutability tests."""

    def __init__(self) -> None:
        self._devices: dict[str, DeviceResponse] = {}

    def add_device(self, device: DeviceResponse) -> DeviceResponse:
        self._devices[device.device_id] = device.model_copy(deep=True)
        return device.model_copy(deep=True)

    def list_devices(self) -> list[DeviceResponse]:
        return [device.model_copy(deep=True) for device in self._devices.values()]

    def get_device(self, device_id: str) -> DeviceResponse | None:
        device = self._devices.get(device_id)
        return device.model_copy(deep=True) if device is not None else None

    def update_status(
        self, device_id: str, status: DeviceStatus
    ) -> DeviceResponse | None:
        device = self._devices.get(device_id)
        if device is None:
            return None
        updated = device.model_copy(update={"status": status}, deep=True)
        self._devices[device_id] = updated
        return updated.model_copy(deep=True)


class RecordingOfflineTransitionHandler:
    """Alternative event handler used to test service substitution."""

    def __init__(self) -> None:
        self.device_ids: list[str] = []

    def handle(self, device_id: str) -> AlertResponse:
        self.device_ids.append(device_id)
        return AlertResponse(
            device_id=device_id,
            message="Recorded by a test handler.",
            timestamp=datetime.now(timezone.utc),
        )


def make_device(
    device_id: str = "RTR-101", status: str = "online"
) -> DeviceCreate:
    return DeviceCreate(
        device_id=device_id,
        name="Branch Router",
        device_type="router",
        ip_address="192.168.10.1",
        status=status,
    )


def make_services(
    device_repository: DeviceRepository | None = None,
    offline_handler: OfflineTransitionHandler | None = None,
) -> tuple[DeviceService, InMemoryAlertRepository]:
    repository = device_repository or InMemoryDeviceRepository()
    alert_repository = InMemoryAlertRepository()
    handler = offline_handler or RepositoryOfflineTransitionHandler(alert_repository)
    service = DeviceService(
        repository,
        handler,
    )
    return service, alert_repository


def test_register_device_returns_device_fields() -> None:
    service, _ = make_services()

    device = service.register(make_device())

    assert device.device_id == "RTR-101"
    assert device.status == "online"


def test_duplicate_device_id_raises_error() -> None:
    service, _ = make_services()
    service.register(make_device())

    with pytest.raises(DeviceAlreadyExistsError):
        service.register(make_device())


def test_missing_device_raises_error() -> None:
    service, _ = make_services()

    with pytest.raises(DeviceNotFoundError):
        service.get("UNKNOWN")


def test_initial_offline_registration_does_not_create_alert() -> None:
    service, alert_repository = make_services()

    service.register(make_device(status="offline"))

    assert alert_repository.list_alerts() == []


def test_online_to_offline_transition_creates_one_utc_alert() -> None:
    service, alert_repository = make_services()
    service.register(make_device())

    device = service.update_status("RTR-101", "offline")
    alerts = alert_repository.list_alerts()

    assert device.status == "offline"
    assert len(alerts) == 1
    assert alerts[0].device_id == "RTR-101"
    assert alerts[0].timestamp.utcoffset() is not None


def test_repeated_offline_update_does_not_create_another_alert() -> None:
    service, alert_repository = make_services()
    service.register(make_device())

    service.update_status("RTR-101", "offline")
    service.update_status("RTR-101", "offline")

    assert len(alert_repository.list_alerts()) == 1


def test_service_accepts_an_alternative_device_repository() -> None:
    service, _ = make_services(DictionaryDeviceRepository())

    registered = service.register(make_device())

    assert service.get(registered.device_id) == registered


def test_service_accepts_an_alternative_transition_handler() -> None:
    handler = RecordingOfflineTransitionHandler()
    service, _ = make_services(offline_handler=handler)
    service.register(make_device())

    service.update_status("RTR-101", "offline")
    service.update_status("RTR-101", "offline")

    assert handler.device_ids == ["RTR-101"]


def test_invalid_ipv4_address_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DeviceCreate(
            device_id="RTR-102",
            name="Invalid Router",
            device_type="router",
            ip_address="999.1.1.1",
        )