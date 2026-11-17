import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Column, Double, Integer, MetaData, String, Table, create_engine, delete, func, insert, select, update
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError


BASE_DIR = Path(__file__).resolve().parent
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


@asynccontextmanager
async def lifespan(app: FastAPI):
	metadata.create_all(engine)
	yield
	engine.dispose()


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


@app.get("/app", include_in_schema=False)
def employee_app():
	return FileResponse(BASE_DIR / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE_DIR / "static", check_dir=False), name="static")