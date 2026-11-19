from fastapi import APIRouter, status
from sqlalchemy import select

from database import DatabaseSession
from models import Department
from schemas import DepartmentCreate, DepartmentOut

router = APIRouter(prefix="/api/departments", tags=["departments"])


@router.get("/", response_model=list[DepartmentOut])
def list_departments(db: DatabaseSession) -> list[DepartmentOut]:
    departments = db.scalars(select(Department).order_by(Department.department_id))
    return [DepartmentOut.model_validate(department) for department in departments]


@router.post("/", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(payload: DepartmentCreate, db: DatabaseSession) -> DepartmentOut:
    department = Department(department_name=payload.department_name)
    db.add(department)
    db.commit()
    db.refresh(department)
    return DepartmentOut.model_validate(department)
