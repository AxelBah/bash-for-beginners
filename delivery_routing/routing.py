from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

from .models import DayPlan, DeliveryRequest, GeocodedLocation


def _nearest_neighbor_route(matrix: List[List[float]], labels: Sequence[str]) -> Tuple[List[str], float]:
    """Return a simple nearest-neighbor route and total drive minutes.

    The matrix should be square and include the origin at index 0.
    Labels must align with matrix indices; label 0 represents the origin and is not
    included in the returned stop order.
    """

    if not matrix or len(matrix) != len(matrix[0]):
        raise ValueError("Matrix must be square and non-empty")

    remaining = set(range(1, len(labels)))
    order: List[int] = []
    drive_minutes = 0.0
    current = 0
    while remaining:
        next_stop = min(remaining, key=lambda idx: matrix[current][idx])
        drive_minutes += matrix[current][next_stop]
        order.append(next_stop)
        remaining.remove(next_stop)
        current = next_stop

    # Return to the depot
    drive_minutes += matrix[current][0]
    return [labels[idx] for idx in order], drive_minutes


def build_day_plan(
    date_label,
    deliveries: Iterable[DeliveryRequest],
    geo_locations: Dict[str, GeocodedLocation],
    depot: GeocodedLocation,
    matrix_builder,
    *,
    service_minutes_per_stop: float = 10.0,
    max_workday_minutes: float = 8 * 60,
) -> DayPlan:
    """Create a :class:`DayPlan` from deliveries scheduled on the same day."""

    requests = list(deliveries)
    if not requests:
        raise ValueError("At least one delivery is required to build a day plan")

    # Build coordinates in order: depot first, then stops
    coordinates = [depot] + [geo_locations[req.postcode] for req in requests]
    labels = ["Depot"] + [req.postcode for req in requests]

    matrix = matrix_builder(coordinates)
    stop_order, drive_minutes = _nearest_neighbor_route(matrix, labels)
    service_minutes = len(requests) * service_minutes_per_stop
    total_minutes = drive_minutes + service_minutes
    feasible = total_minutes <= max_workday_minutes
    reason = None if feasible else f"Estimated {total_minutes:.1f} min exceeds workday limit ({max_workday_minutes} min)"

    return DayPlan(
        date=date_label,
        requests=requests,
        stop_order=stop_order,
        drive_minutes=drive_minutes,
        service_minutes=service_minutes,
        feasible=feasible,
        reason=reason,
    )
