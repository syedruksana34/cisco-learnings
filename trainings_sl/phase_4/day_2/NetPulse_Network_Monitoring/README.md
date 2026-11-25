# NetPulse Network Monitoring API

NetPulse is a practice API for registering routers, switches, and servers. You can list a device, change its online/offline status, and view an alert when it first changes from online to offline.

This project stores data in memory. It does not ping real devices and does not use a database. All devices and alerts are cleared when the server stops or restarts.

## 1. Set Up the Project

Open a terminal at the workspace root (the folder that contains `phase_4`) and run:

```bash
cd phase_4/day_2/NetPulse_Network_Monitoring
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

The activation command is for Linux or macOS. If the terminal says `python` is not found, use `python3` as shown above.

## 2. Run the Tests

Keep the terminal in the `NetPulse_Network_Monitoring` project folder, with `.venv` activated, and run:

```bash
python3 -m pytest -q
```

The tests check device registration, duplicate and missing IDs, IPv4 validation, and offline alert behavior. A passing run ends with `7 passed`.

## 3. Start the API

In the same terminal, run:

```bash
python3 -m uvicorn app.main:app --reload
```

Leave this terminal running. Open the Swagger page in your browser:

[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

If the terminal says port 8000 is already in use, stop the command with `Ctrl+C`, then start the app on port 8001:

```bash
python3 -m uvicorn app.main:app --reload --port 8001
```

In that case, open [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).

## 4. Try the API in Swagger

In Swagger, each endpoint is a row. Expand a row, click **Try it out**, fill in the fields, then click **Execute**.

### Check the server

Expand `GET /health` and click **Execute**. Expect status `200` and:

```json
{"status":"ok"}
```

### Register a device

Expand `POST /devices`. Paste this into the request body and click **Execute**:

```json
{
	"device_id": "RTR-101",
	"name": "Branch Router",
	"device_type": "router",
	"ip_address": "192.168.10.1",
	"status": "online"
}
```

Expect `201 Created`. The device ID must be unique. `device_type` must be `router`, `switch`, or `server`; status must be `online` or `offline`.

### Confirm the device is saved

Expand `GET /devices` and click **Execute**. The response should include `RTR-101`.

You can also expand `GET /devices/{device_id}`, click **Try it out**, enter `RTR-101` in the `device_id` field, then click **Execute**.

### Change the device status and check its alert

1. Expand `PATCH /devices/{device_id}/status` and click **Try it out**.
2. Enter `RTR-101` in the `device_id` field.
3. Use this request body, then click **Execute**:

	 ```json
	 {"status":"offline"}
	 ```

	 Expect `200 OK` and a response showing the device as offline.

4. Execute the same PATCH request one more time.
5. Expand `GET /alerts` and click **Execute**. There should be exactly one alert for `RTR-101`. Repeating the offline update does not create another alert.

### Check error responses (optional)

- Registering `RTR-101` again returns `409 Conflict` because that ID already exists.
- Looking up a device ID that does not exist returns `404 Not Found`.
- Sending an invalid IPv4 address, such as `999.1.1.1`, returns `422 Unprocessable Entity`.

## 5. Stop the API

Return to the terminal running Uvicorn and press `Ctrl+C`. Since storage is in memory, stopping or restarting the API clears all devices and alerts.

## How the Code Is Organized

- `app/routes/devices.py` receives HTTP requests and maps service errors to HTTP status codes.
- `app/services/device_service.py` applies device rules and detects online-to-offline transitions.
- `app/repositories/device_repository.py` stores devices and alerts in memory.
- `app/events.py` creates and saves the timestamped offline alert.
- `app/models.py` validates request data and defines API responses.

These modules run together as one application (a modular monolith). The service depends on repository operations rather than accessing storage directly, so a different repository could be added later without moving business rules into the routes.