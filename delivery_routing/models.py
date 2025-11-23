from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional


@dataclass
class DeliveryRequest:
    """Represents a row from the Google Sheet."""

    recipient: str
    postcode: str
    desired_date: date
    notes: Optional[str] = None


@dataclass
class GeocodedLocation:
    """Lat/lon pair returned by Geoapify along with its identifier."""

    identifier: str
    latitude: float
    longitude: float
    raw: dict


@dataclass
class DayPlan:
    """Plan for a single delivery day."""

    date: date
    requests: List[DeliveryRequest]
    stop_order: List[str]
    drive_minutes: float
    service_minutes: float
    feasible: bool
    reason: Optional[str] = None

    @property
    def total_minutes(self) -> float:
        return self.drive_minutes + self.service_minutes
