from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from database import Base, engine
from routers import departments, students


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="College Management API", lifespan=lifespan)
app.include_router(departments.router)
app.include_router(students.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "College Management API is running"}
