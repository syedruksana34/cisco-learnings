# NetPulse SOLID Design Patterns

This is a separate SOLID-focused version of the NetPulse API. It keeps the same device endpoints and in-memory behavior as `NetPulse_Network_Monitoring`, but depends on small protocols so storage and offline-alert handling can be replaced without changing device business rules.

The API registers routers, switches, and servers; lets clients list or retrieve devices; changes device status; and records one alert when a device transitions from online to offline. It does not ping devices or use a database. Data resets when the server restarts.

## SOLID in This Project

| Principle | Where it appears |
|---|---|
| Single Responsibility | Routes handle HTTP; `DeviceService` handles device rules; `AlertService` handles alert queries; repositories handle storage; the event handler builds and saves transition alerts. |
| Open/Closed | `DeviceService` depends on protocols. A new storage or alert-handler implementation can be added without editing the service. |
| Liskov Substitution | Any implementation that honors `DeviceRepository` or `OfflineTransitionHandler` behavior can be substituted. Tests use alternative implementations. |
| Interface Segregation | Device storage and alert storage have separate small protocols in `app/repositories/contracts.py`. Consumers depend only on the operations they need. |
| Dependency Inversion | High-level services depend on protocols, not `InMemoryDeviceRepository` or `InMemoryAlertRepository`. Concrete objects are assembled in `app/dependencies.py`. |

## Code Map

- `app/models.py`: validated request and response models.
- `app/routes/devices.py`: HTTP endpoints and conversion of service errors to HTTP responses.
- `app/services/device_service.py`: device registration, lookup, and status-transition rules.
- `app/services/alert_service.py`: alert listing use case.
- `app/repositories/contracts.py`: separate `DeviceRepository` and `AlertRepository` protocols.
- `app/repositories/device_repository.py`: in-memory device adapter.
- `app/repositories/alert_repository.py`: in-memory alert adapter.
- `app/events.py`: `OfflineTransitionHandler` protocol and repository-backed alert handler.
- `app/dependencies.py`: composition root that creates and shares concrete implementations.
- `tests/test_device_service.py`: service behavior and replacement-implementation tests.

## Set Up and Test

From the workspace root, run:

```bash
cd phase_4/day_2/NetPulse_SOLID_Design_Patterns
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m pytest -q
```

The tests cover registration, duplicate and missing IDs, IPv4 validation, the single-alert transition rule, and substituting device repositories and event handlers.

## Run and Try the API

Start the app from this project directory:

```bash
python3 -m uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). If port 8000 is busy, use `python3 -m uvicorn app.main:app --reload --port 8001` and open [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).

Use `POST /devices` with this body:

```json
{
  "device_id": "RTR-101",
  "name": "Branch Router",
  "device_type": "router",
  "ip_address": "192.168.10.1",
  "status": "online"
}
```

Then send `{"status":"offline"}` to `PATCH /devices/RTR-101/status` twice. `GET /alerts` should show exactly one alert. The API contract remains the same as the original NetPulse project: six operations, `409` for duplicate IDs, `404` for missing devices, and `422` for invalid input.

This remains a modular monolith: all modules run in one application process. Stop it with `Ctrl+C`; in-memory devices and alerts are cleared when the process stops.