"""FastAPI application entry point for NetPulse."""

from fastapi import FastAPI

from app.routes.devices import router as devices_router

app = FastAPI(title="NetPulse Network Monitoring API", version="1.0.0")
app.include_router(devices_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}