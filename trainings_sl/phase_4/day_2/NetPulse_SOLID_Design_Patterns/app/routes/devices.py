"""HTTP endpoints for devices and status-transition alerts."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_alert_service, get_device_service
from app.models import AlertResponse, DeviceCreate, DeviceResponse, StatusUpdate
from app.services.alert_service import AlertService
from app.services.device_service import (
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    DeviceService,
)

router = APIRouter(tags=["devices"])


@router.post(
    "/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "A device with this ID already exists."}},
)
def register_device(
    device: DeviceCreate,
    service: DeviceService = Depends(get_device_service),
) -> DeviceResponse:
    try:
        return service.register(device)
    except DeviceAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Device {error} is already registered.",
        ) from error


@router.get("/devices", response_model=list[DeviceResponse])
def list_devices(
    service: DeviceService = Depends(get_device_service),
) -> list[DeviceResponse]:
    return service.list_devices()


@router.get(
    "/devices/{device_id}",
    response_model=DeviceResponse,
    responses={404: {"description": "The device does not exist."}},
)
def get_device(
    device_id: str,
    service: DeviceService = Depends(get_device_service),
) -> DeviceResponse:
    try:
        return service.get(device_id)
    except DeviceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device {error} was not found.",
        ) from error


@router.patch(
    "/devices/{device_id}/status",
    response_model=DeviceResponse,
    responses={404: {"description": "The device does not exist."}},
)
def update_device_status(
    device_id: str,
    update: StatusUpdate,
    service: DeviceService = Depends(get_device_service),
) -> DeviceResponse:
    try:
        return service.update_status(device_id, update.status)
    except DeviceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device {error} was not found.",
        ) from error


@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(
    service: AlertService = Depends(get_alert_service),
) -> list[AlertResponse]:
    return service.list_alerts()