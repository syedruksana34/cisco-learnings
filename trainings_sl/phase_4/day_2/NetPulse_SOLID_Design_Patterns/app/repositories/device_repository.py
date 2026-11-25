"""Instance-scoped in-memory storage for devices."""

from app.models import DeviceResponse, DeviceStatus


class InMemoryDeviceRepository:
    """Store devices for the lifetime of the app process."""

    def __init__(self) -> None:
        self._devices: dict[str, DeviceResponse] = {}

    def add_device(self, device: DeviceResponse) -> DeviceResponse:
        stored_device = device.model_copy(deep=True)
        self._devices[stored_device.device_id] = stored_device
        return stored_device.model_copy(deep=True)

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

        updated_device = device.model_copy(update={"status": status}, deep=True)
        self._devices[device_id] = updated_device
        return updated_device.model_copy(deep=True)