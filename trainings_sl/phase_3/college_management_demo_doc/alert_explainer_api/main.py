from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from database import Base, engine
from routers import alerts


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="AI Intelligence Layer -- Alert Explainer API", lifespan=lifespan)
app.include_router(alerts.router)


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "Alert Explainer API is running"}
