import pytest
from pydantic import ValidationError

from app.models import DeviceCreate
from app.repositories.device_repository import InMemoryDeviceRepository
from app.services.device_service import (
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    DeviceService,
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


def make_service() -> DeviceService:
    return DeviceService(InMemoryDeviceRepository())


def test_register_device_returns_device_fields() -> None:
    service = make_service()

    device = service.register(make_device())

    assert device.device_id == "RTR-101"
    assert device.status == "online"


def test_duplicate_device_id_raises_error() -> None:
    service = make_service()
    service.register(make_device())

    with pytest.raises(DeviceAlreadyExistsError):
        service.register(make_device())


def test_missing_device_raises_error() -> None:
    service = make_service()

    with pytest.raises(DeviceNotFoundError):
        service.get("UNKNOWN")


def test_initial_offline_registration_does_not_create_alert() -> None:
    service = make_service()

    service.register(make_device(status="offline"))

    assert service.list_alerts() == []


def test_online_to_offline_transition_creates_one_utc_alert() -> None:
    service = make_service()
    service.register(make_device())

    device = service.update_status("RTR-101", "offline")
    alerts = service.list_alerts()

    assert device.status == "offline"
    assert len(alerts) == 1
    assert alerts[0].device_id == "RTR-101"
    assert alerts[0].timestamp.utcoffset() is not None


def test_repeated_offline_update_does_not_create_another_alert() -> None:
    service = make_service()
    service.register(make_device())

    service.update_status("RTR-101", "offline")
    service.update_status("RTR-101", "offline")

    assert len(service.list_alerts()) == 1


def test_invalid_ipv4_address_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DeviceCreate(
            device_id="RTR-102",
            name="Invalid Router",
            device_type="router",
            ip_address="999.1.1.1",
        )