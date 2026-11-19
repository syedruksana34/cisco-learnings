from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from database import DatabaseSession
from models import Department, Student
from schemas import StudentCreate, StudentOut

router = APIRouter(prefix="/api/students", tags=["students"])


@router.get("/", response_model=list[StudentOut])
def list_students(db: DatabaseSession) -> list[StudentOut]:
    query = (
        select(Student)
        .options(joinedload(Student.department))
        .order_by(Student.student_id)
    )
    return [StudentOut.model_validate(student) for student in db.scalars(query)]


@router.post("/", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def create_student(payload: StudentCreate, db: DatabaseSession) -> StudentOut:
    department = db.get(Department, payload.department_id)
    if department is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Department not found",
        )

    student = Student(student_name=payload.student_name, department=department)
    db.add(student)
    db.commit()
    db.refresh(student)
    return StudentOut.model_validate(student)
