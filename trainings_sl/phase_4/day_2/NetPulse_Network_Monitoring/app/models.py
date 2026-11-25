"""Validated API models for devices and alerts."""

from datetime import datetime
from ipaddress import IPv4Address
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DeviceType = Literal["router", "switch", "server"]
DeviceStatus = Literal["online", "offline"]


class DeviceCreate(BaseModel):
    """Fields required to register a network device."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "device_id": "RTR-101",
                    "name": "Branch Router",
                    "device_type": "router",
                    "ip_address": "192.168.10.1",
                    "status": "online",
                }
            ]
        }
    )

    device_id: str = Field(min_length=1, examples=["RTR-101"])
    name: str = Field(min_length=1, examples=["Branch Router"])
    device_type: DeviceType = Field(examples=["router"])
    ip_address: str = Field(examples=["192.168.10.1"])
    status: DeviceStatus = Field(default="online", examples=["online"])

    @field_validator("ip_address")
    @classmethod
    def validate_ipv4(cls, value: str) -> str:
        try:
            IPv4Address(value)
        except ValueError as error:
            raise ValueError("ip_address must be a valid IPv4 address") from error
        return value


class DeviceResponse(BaseModel):
    """A registered device returned by the API."""

    device_id: str
    name: str
    device_type: DeviceType
    ip_address: str
    status: DeviceStatus


class StatusUpdate(BaseModel):
    """Payload for changing a device's status."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"status": "offline"}]}
    )

    status: DeviceStatus = Field(examples=["offline"])


class AlertResponse(BaseModel):
    """Alert emitted when a device transitions from online to offline."""

    device_id: str
    message: str
    timestamp: datetime