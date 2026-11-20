from collections import OrderedDict
from contextlib import asynccontextmanager, closing, contextmanager
from pathlib import Path
import sqlite3
from time import monotonic
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field


class EmployeeInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    designation: str = Field(min_length=1, max_length=80)
    age: int = Field(ge=18, le=100)
    salary: float = Field(ge=0, allow_inf_nan=False)


class AgentMessage(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    session_id: UUID | None = None


DATABASE = Path(__file__).with_name("employees.sqlite3")


@contextmanager
def database():
    with closing(sqlite3.connect(DATABASE)) as connection, connection:
        connection.row_factory = sqlite3.Row
        yield connection


@asynccontextmanager
async def lifespan(app: FastAPI):
    with database() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                designation TEXT NOT NULL, age INTEGER NOT NULL, salary REAL NOT NULL
            )
        """)
    app.state.pending_deletes = {}
    app.state.conversations = OrderedDict()
    yield


app = FastAPI(title="Employee Operations", lifespan=lifespan)


def get_record(connection: sqlite3.Connection, employee_id: int) -> dict:
    row = connection.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Employee not found.")
    return dict(row)


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(Path(__file__).with_name("index.html"))


@app.get("/api/employees", tags=["Read Agent"])
def list_employees(search: str = ""):
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM employees WHERE instr(lower(name), lower(?)) > 0 "
            "OR instr(lower(designation), lower(?)) > 0 ORDER BY id",
            (search.strip(), search.strip()),
        )
        return [dict(row) for row in rows]


@app.get("/api/employees/{employee_id}", tags=["Read Agent"])
def read_employee(employee_id: int):
    with database() as connection:
        return get_record(connection, employee_id)


@app.post("/api/employees", status_code=201, tags=["Write Agent"])
def create_employee(employee: EmployeeInput):
    with database() as connection:
        cursor = connection.execute(
            "INSERT INTO employees (name, designation, age, salary) VALUES (?, ?, ?, ?)",
            (employee.name, employee.designation, employee.age, employee.salary),
        )
        return get_record(connection, cursor.lastrowid)


@app.put("/api/employees/{employee_id}", tags=["Write Agent"])
def update_employee(employee_id: int, employee: EmployeeInput):
    with database() as connection:
        connection.execute(
            "UPDATE employees SET name = ?, designation = ?, age = ?, salary = ? WHERE id = ?",
            (employee.name, employee.designation, employee.age, employee.salary, employee_id),
        )
        return get_record(connection, employee_id)


@app.post("/api/employees/{employee_id}/deletion", tags=["Delete Agent"])
async def prepare_delete(employee_id: int, request: Request):
    from starlette.concurrency import run_in_threadpool

    employee = await run_in_threadpool(read_employee, employee_id)
    now = monotonic()
    pending = request.app.state.pending_deletes
    for token, (expires, _) in list(pending.items()):
        if expires <= now:
            pending.pop(token)
    token = uuid4()
    pending[token] = (now + 300, employee)
    return {"confirmation_id": token, "employee": employee}


@app.delete("/api/deletions/{confirmation_id}", status_code=204, tags=["Delete Agent"])
async def confirm_delete(confirmation_id: UUID, request: Request):
    from starlette.concurrency import run_in_threadpool

    proposal = request.app.state.pending_deletes.pop(confirmation_id, None)
    if proposal is None or proposal[0] <= monotonic():
        raise HTTPException(409, "Deletion confirmation is missing or expired.")
    await run_in_threadpool(delete_unchanged_employee, proposal[1])
    return Response(status_code=204)


def delete_unchanged_employee(employee: dict):
    with database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if get_record(connection, employee["id"]) != employee:
            raise HTTPException(409, "Employee changed. Review the record and confirm again.")
        connection.execute("DELETE FROM employees WHERE id = ?", (employee["id"],))


@app.post("/api/supervisor", tags=["Supervisor Agent"])
async def ask_supervisor(payload: AgentMessage, request: Request):
    from .main import run_supervisor

    if not payload.message.strip():
        raise HTTPException(422, "Enter a request for the supervisor.")
    message = payload.message.strip()
    if payload.session_id is None:
        return await run_supervisor(message, request.app)
    sessions = request.app.state.conversations
    history = sessions.get(payload.session_id, [])
    result = await run_supervisor(message, request.app, history)
    data = result.get("data")
    if result.get("operation") == "delete":
        summary = "Deletion preview shown. The employee is not deleted by this chat response."
    elif isinstance(data, list):
        summary = "; ".join(f"{row['name']} (employee ID {row['id']})" for row in data[:10]) or "No matching employees."
    else:
        summary = result.get("reply") or str(data)
    sessions[payload.session_id] = (history + [
        {"role": "user", "content": message}, {"role": "assistant", "content": summary[:700]},
    ])[-6:]
    sessions.move_to_end(payload.session_id)
    if len(sessions) > 128:
        sessions.popitem(last=False)
    return result