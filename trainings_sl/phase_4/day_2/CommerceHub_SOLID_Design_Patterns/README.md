# CommerceHub - SOLID and Design Patterns

CommerceHub is a small FastAPI Order Management API that demonstrates layered architecture, the Single Responsibility Principle, dependency inversion, the Repository pattern, and FastAPI dependency injection. This project continues the Hands-on 01 CommerceHub API without changing its public endpoints or request/response fields.

## Learning Objectives

After this hands-on, you should be able to explain:

- How a FastAPI application handles HTTP requests.
- How Pydantic validates API request data.
- How a service layer calculates business values.
- How a repository stores and retrieves data.
- How responsibilities flow through an application in separate layers.
- How an order repository Protocol decouples business logic from storage.
- How FastAPI `Depends` provides a shared service instance.

## Project Structure

```text
CommerceHub_SOLID_Design_Patterns/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── models.py
│   ├── service.py
│   └── repository.py
├── tests/
│   └── test_service.py
├── requirements.txt
└── README.md
```

| File | Responsibility |
|---|---|
| `app/main.py` | Defines the FastAPI application and HTTP routes. |
| `app/models.py` | Defines Pydantic request and response models. |
| `app/service.py` | Implements business logic and order total calculation. |
| `app/repository.py` | Defines the `OrderRepository` contract and in-memory implementation. |
| `tests/test_service.py` | Tests order total calculation and save/list behavior. |
| `requirements.txt` | Lists application dependencies and pytest. |

## Architecture Flow

```text
Swagger / HTTP Client
          |
          v
app/main.py
          |
          v
app/models.py - request validation
          |
          v
app/service.py - calculate_total() and order rules
          |
          v
app/repository.py - OrderRepository contract
          |
          v
InMemoryOrderRepository - assign ID and store order
          |
          v
app/main.py - return HTTP response
```

### Responsibility of Each Layer

**API layer: `main.py`**

- Creates the FastAPI application.
- Defines endpoints.
- Receives requests and returns HTTP responses.
- Does not calculate totals or directly manage the order list.

**Model layer: `models.py`**

- Defines the structure of request and response data.
- Validates values before business logic executes.
- `quantity` must be greater than `0`.
- `unit_price` must be greater than or equal to `0`.
- An order must contain at least one item.

**Business layer: `service.py`**

- Receives an `OrderRequest`.
- Calculates the total in `calculate_total()` as the sum of `quantity * unit_price`.
- Rounds the total to two decimal places.
- Sends the completed order to the repository.

**Storage layer: `repository.py`**

- Defines the `OrderRepository` Protocol used by the service.
- `InMemoryOrderRepository` stores orders in an in-memory Python list.
- Assigns the next sequential order ID.
- Returns saved orders when requested.

**Dependency injection: `main.py`**

- Uses FastAPI `Depends` to provide `OrderService` to the order endpoints.
- Shares one service and in-memory repository across requests until the server restarts.

## Prerequisites

- Ubuntu/Linux
- Python 3
- A terminal
- A web browser

## Setup and Run

Open a terminal and run:

```bash
cd /home/ruksyed615/Desktop/cisco-learnings/trainings_sl/phase_4/day_2/CommerceHub_SOLID_Design_Patterns
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Keep the terminal open while using the API.

When the server shows `Application startup complete`, open Swagger UI:

[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

Stop the server with `Ctrl+C`.

Run the service tests from the project root with:

```bash
python -m pytest -q
```

To start the server again later:

```bash
cd /home/ruksyed615/Desktop/cisco-learnings/trainings_sl/phase_4/day_2/CommerceHub_SOLID_Design_Patterns
source .venv/bin/activate
python -m uvicorn app.main:app --reload
```

## API Endpoints

| Method | Endpoint | Purpose | Success Status |
|---|---|---|---|
| `GET` | `/health` | Checks API availability | `200 OK` |
| `POST` | `/orders` | Creates a new order | `201 Created` |
| `GET` | `/orders` | Lists all saved orders | `200 OK` |

## Testing in Swagger

### 1. Test API Health

1. Open `http://127.0.0.1:8000/docs`.
2. Expand `GET /health`.
3. Select **Try it out**.
4. Select **Execute**.

Expected response:

```json
{
  "status": "ok"
}
```

### 2. Create an Order

1. Expand `POST /orders`.
2. Select **Try it out**.
3. Enter the following JSON:

```json
{
  "customer_name": "John",
  "items": [
    {
      "name": "Notebook",
      "quantity": 2,
      "unit_price": 50
    },
    {
      "name": "Pen",
      "quantity": 1,
      "unit_price": 20
    }
  ]
}
```

4. Select **Execute**.

Expected result:

- HTTP status: `201 Created`
- Order ID: `1`
- Customer: `John`
- Total: `120.0`

Calculation:

```text
(2 x 50) + (1 x 20) = 120
```

### 3. Retrieve Saved Orders

1. Expand `GET /orders`.
2. Select **Try it out**.
3. Select **Execute**.

The response should contain the order created in the previous step.

### 4. Test Invalid Input

1. Expand `POST /orders`.
2. Select **Try it out**.
3. Enter an item with quantity `0`:

```json
{
  "customer_name": "John",
  "items": [
    {
      "name": "Notebook",
      "quantity": 0,
      "unit_price": 50
    }
  ]
}
```

4. Select **Execute**.

Expected result:

- HTTP status: `422 Unprocessable Entity`
- Pydantic validation explains that `quantity` must be greater than `0`.

## Testing from the Terminal

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Create an order:

```bash
curl -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"customer_name":"John","items":[{"name":"Notebook","quantity":2,"unit_price":50},{"name":"Pen","quantity":1,"unit_price":20}]}'
```

List orders:

```bash
curl http://127.0.0.1:8000/orders
```

Test invalid quantity:

```bash
curl -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"customer_name":"John","items":[{"name":"Notebook","quantity":0,"unit_price":50}]}'
```

## Important Behavior

The repository uses in-memory storage. Orders disappear when the server restarts or stops. This hands-on does not use a database, authentication, or frontend.

## Presentation Summary

The API receives a customer order in `main.py`. Pydantic validates the request in `models.py`. `service.py` calculates the order total. `repository.py` assigns an ID and stores the order. The response then travels back through `main.py` to Swagger or the HTTP client.
