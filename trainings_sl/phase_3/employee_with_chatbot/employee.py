import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Column, Double, Integer, MetaData, String, Table, create_engine, delete, func, insert, select, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
logger = logging.getLogger(__name__)
database_url = os.getenv("DATABASE_URL") or URL.create(
	"mysql+pymysql",
	username=os.getenv("MYSQL_USER", "root"),
	password=os.getenv("MYSQL_PASSWORD", ""),
	host=os.getenv("MYSQL_HOST", "127.0.0.1"),
	port=int(os.getenv("MYSQL_PORT", "3306")),
	database=os.getenv("MYSQL_DATABASE", "employee_management"),
	query={"charset": "utf8mb4"},
)
engine = create_engine(database_url, pool_pre_ping=True)
metadata = MetaData()
employees = Table(
	"employees", metadata,
	Column("id", Integer, primary_key=True, autoincrement=False),
	Column("name", String(30), nullable=False),
	Column("age", Integer, nullable=False),
	Column("salary", Double, nullable=False),
	Column("desig", String(30), nullable=False),
)

# The chatbot's SQL tool uses its own engine so it can point at a least-privilege, read-only database account.
chat_sql_url = make_url(os.getenv("CHATBOT_DATABASE_URL") or database_url)
chat_sql_engine = create_engine(
	chat_sql_url,
	pool_pre_ping=True,
	connect_args={"init_command": "SET SESSION max_execution_time=5000"} if chat_sql_url.get_backend_name() == "mysql" else {},
)


@asynccontextmanager
async def lifespan(app: FastAPI):
	metadata.create_all(engine)
	yield
	engine.dispose()
	chat_sql_engine.dispose()


app = FastAPI(title="Employee Management System", lifespan=lifespan)


class Employee(BaseModel):
	id: int = Field(gt=0)
	name: str = Field(min_length=3, max_length=30)
	age: int = Field(ge=18, le=60)
	salary: float = Field(ge=25000, allow_inf_nan=False)
	desig: str = Field(min_length=3, max_length=30)


class SalaryUpdate(BaseModel):
	salary: float = Field(ge=25000, allow_inf_nan=False)


class EmployeeException(Exception):
	def __init__(self, status_code: int, message: str):
		self.status_code = status_code
		self.message = message


@app.exception_handler(EmployeeException)
async def employee_exception_handler(request: Request, exc: EmployeeException):
	return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
	return JSONResponse(
		status_code=400,
		content=jsonable_encoder({"error": "Validation Failed", "details": exc.errors()}),
	)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
	logger.exception("Unhandled error processing request")
	return JSONResponse(status_code=500, content={"error": "Internal Server Error"})


def get_employee(connection, employee_id: int):
	row = connection.execute(select(employees).where(employees.c.id == employee_id)).mappings().first()
	if row is None:
		raise EmployeeException(404, "Employee Not Found")
	return dict(row)


@app.get("/")
def welcome():
	return {"message": "Welcome to Employee Management System"}


@app.post("/addEmployee", status_code=201)
def add_employee(emp: Employee):
	try:
		with engine.begin() as connection:
			connection.execute(insert(employees).values(**emp.model_dump()))
	except IntegrityError as exc:
		with engine.connect() as connection:
			if connection.execute(select(employees.c.id).where(employees.c.id == emp.id)).first():
				raise EmployeeException(400, "Employee ID Already Exists") from exc
		raise
	return {"message": "Employee Added Successfully", "employee": emp}


@app.get("/getAllEmployees")
def get_all_employees():
	with engine.connect() as connection:
		result = [dict(row) for row in connection.execute(select(employees).order_by(employees.c.id)).mappings()]
	if not result:
		raise EmployeeException(404, "No Employees Available")
	return result


@app.get("/employeeByID/{id}")
def employee_by_id(id: int):
	with engine.connect() as connection:
		return get_employee(connection, id)


@app.get("/employeeByName/{name}")
def employee_by_name(name: str):
	with engine.connect() as connection:
		result = [dict(row) for row in connection.execute(
			select(employees).where(func.lower(employees.c.name) == name.lower()).order_by(employees.c.id)
		).mappings()]
	if not result:
		raise EmployeeException(404, "Employee Name Not Found")
	return result


@app.get("/employeeByDesignation/{desig}")
def employee_by_designation(desig: str):
	with engine.connect() as connection:
		result = [dict(row) for row in connection.execute(
			select(employees).where(func.lower(employees.c.desig) == desig.lower()).order_by(employees.c.id)
		).mappings()]
	if not result:
		raise EmployeeException(404, "Designation Not Found")
	return result


@app.put("/updateEmployee/{id}")
def update_employee(id: int, emp: Employee):
	with engine.begin() as connection:
		get_employee(connection, id)
		if emp.id != id:
			raise EmployeeException(400, "Employee ID Cannot Be Changed")
		connection.execute(update(employees).where(employees.c.id == id).values(**emp.model_dump()))
	return {"message": "Employee Updated Successfully", "employee": emp}


@app.patch("/updateSalary/{id}")
def update_salary(id: int, data: SalaryUpdate):
	with engine.begin() as connection:
		result = connection.execute(update(employees).where(employees.c.id == id).values(salary=data.salary))
		if result.rowcount == 0:
			raise EmployeeException(404, "Employee Not Found")
		emp = get_employee(connection, id)
	return {"message": "Salary Updated Successfully", "employee": emp}


@app.delete("/deleteEmployee/{id}")
def delete_employee(id: int):
	with engine.begin() as connection:
		result = connection.execute(delete(employees).where(employees.c.id == id))
		if result.rowcount == 0:
			raise EmployeeException(404, "Employee Not Found")
	return {"message": "Employee Deleted Successfully"}


@app.delete("/deleteAllEmployees")
def delete_all_employees():
	with engine.begin() as connection:
		result = connection.execute(delete(employees))
		if result.rowcount == 0:
			raise EmployeeException(404, "No Employees Available")
	return {"message": "All Employees Deleted Successfully"}


# ---------------------------------------------------------------------------
# Gemini chatbot
# ---------------------------------------------------------------------------

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# Used while the primary model is rate-limited or unavailable; set to an empty value to disable.
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash").strip()
GEMINI_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "30")) * 1000
PRIMARY_MODEL_COOLDOWN_SECONDS = 300
primary_model_unavailable_until = 0.0
MAX_TOOL_ROUNDS = 8
MAX_SQL_ROWS = 200
FORBIDDEN_SQL = re.compile(
	r"\b(insert|update|delete|replace|merge|create|alter|drop|truncate|rename|grant|revoke|set|call|do|handler|load|lock|unlock"
	r"|into\s+outfile|into\s+dumpfile|load_file|sleep|benchmark|get_lock|information_schema|performance_schema|mysql|sys)\b",
	re.IGNORECASE,
)

SYSTEM_INSTRUCTION = """You are the assistant built into the "people." Employee Management System web application.
Answer questions about this application and its employee data. Politely decline unrelated requests.

Data model: MySQL table `employees` with columns
  id INT primary key (positive, chosen by the user, cannot be changed after creation),
  name VARCHAR(30) (3-30 characters), age INT (18-60), salary DOUBLE (minimum 25000), desig VARCHAR(30) (designation/job title, 3-30 characters).

REST API of the application:
  GET /getAllEmployees, GET /employeeByID/{id}, GET /employeeByName/{name} (exact, case-insensitive),
  GET /employeeByDesignation/{desig} (exact, case-insensitive), POST /addEmployee, PUT /updateEmployee/{id},
  PATCH /updateSalary/{id}, DELETE /deleteEmployee/{id}, DELETE /deleteAllEmployees. Interactive docs are at /docs.

Web UI (/app): employee directory table with search (press "/" to focus), "Add employee" button, per-row actions to
edit, update salary or delete, a "Delete all" button, and overview cards (total employees, distinct designations, average salary).

Rules:
- Never invent employee data. Always use the tools to fetch current data before answering data questions.
- Use the REST tools for simple lookups and run_sql_query for aggregations, filtering, ranking, partial matches or statistics
  (e.g. AVG, COUNT, GROUP BY, LIKE). SQL must be a single read-only SELECT against the `employees` table.
- Before calling add_employee, update_employee, update_salary or delete_employee, summarise the exact change and ask the user
  to confirm. Only call the tool after the user has explicitly confirmed in a later message.
- You cannot delete all employees; tell the user to use the "Delete all" button in the directory instead.
- Report tool errors (such as validation failures or "Employee Not Found") clearly to the user.
- Keep answers concise. Use Markdown lists or tables for multiple employees. Format salaries with thousands separators."""

EMPLOYEE_PROPERTIES = {
	"id": {"type": "integer", "description": "Employee ID (positive integer)."},
	"name": {"type": "string", "description": "Full name, 3-30 characters."},
	"age": {"type": "integer", "description": "Age between 18 and 60."},
	"salary": {"type": "number", "description": "Salary, at least 25000."},
	"desig": {"type": "string", "description": "Designation / job title, 3-30 characters."},
}


def _function(name: str, description: str, properties: dict | None = None, required: list[str] | None = None):
	return types.FunctionDeclaration(
		name=name,
		description=description,
		parameters_json_schema={"type": "object", "properties": properties or {}, "required": required or []},
	)


CHAT_TOOLS = types.Tool(function_declarations=[
	_function("get_all_employees", "REST GET /getAllEmployees. Returns every employee ordered by ID."),
	_function("get_employee_by_id", "REST GET /employeeByID/{id}. Returns one employee.",
		{"id": EMPLOYEE_PROPERTIES["id"]}, ["id"]),
	_function("get_employees_by_name", "REST GET /employeeByName/{name}. Exact, case-insensitive name match.",
		{"name": EMPLOYEE_PROPERTIES["name"]}, ["name"]),
	_function("get_employees_by_designation", "REST GET /employeeByDesignation/{desig}. Exact, case-insensitive designation match.",
		{"desig": EMPLOYEE_PROPERTIES["desig"]}, ["desig"]),
	_function("add_employee", "REST POST /addEmployee. Creates an employee. Requires prior explicit user confirmation.",
		EMPLOYEE_PROPERTIES, list(EMPLOYEE_PROPERTIES)),
	_function("update_employee", "REST PUT /updateEmployee/{id}. Replaces all fields of an existing employee (id unchanged). "
		"Fetch the employee first to fill unchanged fields. Requires prior explicit user confirmation.",
		EMPLOYEE_PROPERTIES, list(EMPLOYEE_PROPERTIES)),
	_function("update_salary", "REST PATCH /updateSalary/{id}. Changes only the salary. Requires prior explicit user confirmation.",
		{"id": EMPLOYEE_PROPERTIES["id"], "salary": EMPLOYEE_PROPERTIES["salary"]}, ["id", "salary"]),
	_function("delete_employee", "REST DELETE /deleteEmployee/{id}. Permanently deletes one employee. Requires prior explicit user confirmation.",
		{"id": EMPLOYEE_PROPERTIES["id"]}, ["id"]),
	_function("run_sql_query", "Runs one read-only SQL SELECT (MySQL dialect) against the `employees` table and returns the rows "
		f"(at most {MAX_SQL_ROWS}). Use for aggregations, statistics, ranking, partial matches and complex filters.",
		{"sql": {"type": "string", "description": "A single SELECT statement, e.g. SELECT desig, AVG(salary) FROM employees GROUP BY desig"}},
		["sql"]),
])
WRITE_TOOLS = {"add_employee", "update_employee", "update_salary", "delete_employee"}


class ChatMessage(BaseModel):
	role: Literal["user", "assistant"]
	content: str = Field(min_length=1, max_length=4000)

	@field_validator("content")
	@classmethod
	def trim_content(cls, value: str) -> str:
		value = value.strip()
		if not value:
			raise ValueError("Message content cannot be blank.")
		return value


class ChatRequest(BaseModel):
	messages: list[ChatMessage] = Field(min_length=1, max_length=20)

	@model_validator(mode="after")
	def validate_conversation(self) -> "ChatRequest":
		if self.messages[-1].role != "user":
			raise ValueError("The latest message must be from the user.")
		if sum(len(message.content) for message in self.messages) > 20000:
			raise ValueError("Conversation content must not exceed 20,000 characters.")
		return self


def run_read_only_sql(sql: str) -> dict[str, Any]:
	statement = sql.strip().rstrip(";").strip()
	if not re.match(r"^(select|with)\b", statement, re.IGNORECASE):
		return {"error": "Only a single SELECT statement is allowed."}
	if ";" in statement or "--" in statement or "/*" in statement or "#" in statement:
		return {"error": "Multiple statements and comments are not allowed."}
	if FORBIDDEN_SQL.search(statement):
		return {"error": "The query uses a keyword or schema that is not allowed. Query only the employees table with SELECT."}
	if not re.search(r"\bemployees\b", statement, re.IGNORECASE):
		return {"error": "The query must read from the employees table."}
	try:
		with chat_sql_engine.connect() as connection:
			if chat_sql_engine.dialect.name == "mysql":
				connection.exec_driver_sql("START TRANSACTION READ ONLY")
			elif chat_sql_engine.dialect.name == "sqlite":
				connection.exec_driver_sql("PRAGMA query_only = ON")
			try:
				result = connection.execute(text(statement))
				columns = list(result.keys())
				rows = result.fetchmany(MAX_SQL_ROWS + 1)
			finally:
				connection.rollback()
				if chat_sql_engine.dialect.name == "sqlite":
					connection.exec_driver_sql("PRAGMA query_only = OFF")
	except SQLAlchemyError as exc:
		logger.info("Chatbot SQL query failed: %s", exc)
		return {"error": f"SQL error: {getattr(exc, 'orig', exc)}"}
	truncated = len(rows) > MAX_SQL_ROWS
	data = [
		{column: float(value) if isinstance(value, Decimal) else value for column, value in zip(columns, row)}
		for row in rows[:MAX_SQL_ROWS]
	]
	return {"columns": columns, "rows": jsonable_encoder(data), "row_count": len(data), "truncated": truncated}


async def call_rest_api(method: str, path: str, body: dict | None = None) -> dict[str, Any]:
	# Requests go through this application's own REST endpoints (validation, error handlers and all) without a network hop.
	transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
	async with httpx.AsyncClient(transport=transport, base_url="http://employee-app") as client:
		response = await client.request(method, path, json=body)
	try:
		payload = response.json()
	except ValueError:
		payload = response.text
	return {"status_code": response.status_code, "ok": response.is_success, "body": payload}


async def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
	try:
		if name == "get_all_employees":
			return await call_rest_api("GET", "/getAllEmployees")
		if name == "get_employee_by_id":
			return await call_rest_api("GET", f"/employeeByID/{int(args['id'])}")
		if name == "get_employees_by_name":
			return await call_rest_api("GET", f"/employeeByName/{quote(str(args['name']), safe='')}")
		if name == "get_employees_by_designation":
			return await call_rest_api("GET", f"/employeeByDesignation/{quote(str(args['desig']), safe='')}")
		if name == "add_employee":
			return await call_rest_api("POST", "/addEmployee", {key: args.get(key) for key in EMPLOYEE_PROPERTIES})
		if name == "update_employee":
			return await call_rest_api("PUT", f"/updateEmployee/{int(args['id'])}", {key: args.get(key) for key in EMPLOYEE_PROPERTIES})
		if name == "update_salary":
			return await call_rest_api("PATCH", f"/updateSalary/{int(args['id'])}", {"salary": args.get("salary")})
		if name == "delete_employee":
			return await call_rest_api("DELETE", f"/deleteEmployee/{int(args['id'])}")
		if name == "run_sql_query":
			return run_read_only_sql(str(args.get("sql", "")))
	except (KeyError, TypeError, ValueError) as exc:
		return {"error": f"Invalid arguments for {name}: {exc}"}
	return {"error": f"Unknown tool: {name}"}


@app.post("/api/chat")
async def chat(request: ChatRequest):
	global primary_model_unavailable_until
	api_key = os.getenv("GEMINI_API_KEY", "").strip()
	if not api_key:
		raise EmployeeException(503, "The assistant is not configured. Set GEMINI_API_KEY in employee_with_chatbot/.env and restart the server.")

	contents: list[types.Content] = [
		types.Content(role="user" if message.role == "user" else "model", parts=[types.Part.from_text(text=message.content)])
		for message in request.messages
	]
	config = types.GenerateContentConfig(
		system_instruction=SYSTEM_INSTRUCTION,
		tools=[CHAT_TOOLS],
		automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
	)
	data_changed = False
	try:
		http_options = types.HttpOptions(
			timeout=GEMINI_TIMEOUT_MS,
			retry_options=types.HttpRetryOptions(attempts=2, initial_delay=1.0, max_delay=4.0),
		)
		async with genai.Client(api_key=api_key, http_options=http_options).aio as client:
			use_fallback = GEMINI_FALLBACK_MODEL and time.monotonic() < primary_model_unavailable_until
			model = GEMINI_FALLBACK_MODEL if use_fallback else GEMINI_MODEL
			for _ in range(MAX_TOOL_ROUNDS):
				try:
					response = await client.models.generate_content(model=model, contents=contents, config=config)
				except errors.APIError as exc:
					if exc.code not in (429, 500, 503, 504) or not GEMINI_FALLBACK_MODEL or model == GEMINI_FALLBACK_MODEL:
						raise
					logger.warning("Gemini model %s unavailable (%s); using %s for %ss", model, exc.code, GEMINI_FALLBACK_MODEL, PRIMARY_MODEL_COOLDOWN_SECONDS)
					primary_model_unavailable_until = time.monotonic() + PRIMARY_MODEL_COOLDOWN_SECONDS
					model = GEMINI_FALLBACK_MODEL
					response = await client.models.generate_content(model=model, contents=contents, config=config)
				function_calls = response.function_calls or []
				if not function_calls:
					break
				# Keep the model's turn verbatim so thought signatures are sent back to Gemini.
				contents.append(response.candidates[0].content)
				parts = []
				for call in function_calls:
					result = await execute_tool(call.name, dict(call.args or {}))
					if call.name in WRITE_TOOLS and result.get("ok"):
						data_changed = True
					logger.info("Chatbot tool %s -> %s", call.name, "ok" if result.get("ok", "error" not in result) else "error")
					parts.append(types.Part.from_function_response(name=call.name, response={"result": json.loads(json.dumps(result, default=str))}))
				contents.append(types.Content(role="user", parts=parts))
			else:
				return {"reply": "I needed too many steps to answer that. Please try a more specific question.", "data_changed": data_changed, "model": model, "fallback_used": model != GEMINI_MODEL}
	except errors.APIError as exc:
		logger.warning("Gemini model %s request failed with status %s", model, exc.code)
		if exc.code == 429:
			raise EmployeeException(
				429,
				f"Gemini quota or rate limit reached for {model}. Check usage and quota reset times at "
				"https://ai.dev/rate-limit, or enable billing for your Google AI project. "
				"Daily quota exhaustion requires waiting for the reset; repeated retries will not fix it.",
			) from exc
		if exc.code in (500, 503, 504):
			raise EmployeeException(503, "Gemini is temporarily overloaded. Please try again in a moment.") from exc
		if exc.code == 404:
			raise EmployeeException(502, f"The Gemini model '{GEMINI_MODEL}' is unavailable for this API key. Check GEMINI_MODEL.") from exc
		if exc.code in (400, 401, 403):
			raise EmployeeException(502, "Gemini rejected the request. Check the API key and model settings.") from exc
		raise EmployeeException(502, "Gemini could not complete the request. Check the server logs.") from exc
	except (httpx.RequestError, OSError, TimeoutError) as exc:
		logger.exception("Gemini connection failed")
		raise EmployeeException(502, "Could not connect to Gemini. Check the server logs.") from exc

	if not response.text:
		raise EmployeeException(502, "Gemini returned no answer. The response may have been blocked or incomplete.")
	return {"reply": response.text, "data_changed": data_changed, "model": model, "fallback_used": model != GEMINI_MODEL}


@app.get("/app", include_in_schema=False)
def employee_app():
	return FileResponse(BASE_DIR / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static", check_dir=False), name="static")
