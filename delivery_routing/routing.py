from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

import math
from .models import DayPlan, DeliveryRequest, GeocodedLocation


# --------------------------
# Haversine distance (km)
# --------------------------

def _haversine(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    R = 6371
    lat1, lon1 = a
    lat2, lon2 = b

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lat2 - lon1)

    h = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)

    return 2 * R * math.asin(math.sqrt(h))


# --------------------------
# Nearest Neighbor Route
# --------------------------

def _nearest_neighbor_order(coords: List[Tuple[float, float]]) -> List[int]:
    """
    Returns a list of indices in the order visited.
    coords[0] = depot.
    Uses pure Haversine distance (fast, no API calls).
    """
    n = len(coords)
    unvisited = set(range(1, n))
    order = [0]
    current = 0

    while unvisited:
        nxt = min(unvisited, key=lambda i: _haversine(coords[current], coords[i]))
        order.append(nxt)
        unvisited.remove(nxt)
        current = nxt

    return order


# --------------------------
# Build a SMALL edge list
# --------------------------

def _build_edges(coordinates: List[GeocodedLocation]):
    """
    Build a SAFE and SMALL set of edges for Geoapify.
    This prevents full NxN matrix requests.

    Includes only:
      - depot → all stops
      - nearest-neighbor chain between stops
      - last stop → depot
    """

    n = len(coordinates)
    edges = set()

    # Convert to (lat, lon) for NN logic
    coords_latlon = [(loc.latitude, loc.longitude) for loc in coordinates]

    depot = 0

    # 1. Depot → all stops
    for i in range(1, n):
        edges.add((depot, i))

    # 2. Nearest-neighbor chain
    unvisited = set(range(1, n))
    current = depot

    while unvisited:
        next_idx = min(
            unvisited,
            key=lambda j: _haversine(coords_latlon[current], coords_latlon[j])
        )
        edges.add((current, next_idx))
        current = next_idx
        unvisited.remove(next_idx)

    # Last stop → depot
    edges.add((current, depot))

    return edges


# --------------------------
# Route length helper
# --------------------------

def _route_length(order: List[int], coords: List[Tuple[float, float]]) -> float:
    return sum(_haversine(coords[a], coords[b]) for a, b in zip(order, order[1:]))


# --------------------------
# 2-opt improvement
# --------------------------

def _two_opt(order: List[int], coords: List[Tuple[float, float]]) -> List[int]:
    improved = True
    best = order
    best_len = _route_length(best, coords)

    while improved:
        improved = False
        for i in range(1, len(best) - 2):
            for j in range(i + 1, len(best) - 1):
                new_route = best[:i] + best[i:j][::-1] + best[j:]
                new_len = _route_length(new_route, coords)
                if new_len < best_len:
                    best = new_route
                    best_len = new_len
                    improved = True

    return best


# --------------------------
# Build daily plan
# --------------------------

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

    requests = list(deliveries)
    if not requests:
        raise ValueError("At least one delivery is required to build a day plan")

    # ------------------------------
    # Build coordinate list
    # ------------------------------
    coordinates = [depot] + [geo_locations[r.postcode] for r in requests]
    labels = ["Depot"] + [r.postcode for r in requests]

    # ------------------------------
    # Build Haversine route order
    # ------------------------------
    coords_latlon = [(loc.latitude, loc.longitude) for loc in coordinates]

    order = _nearest_neighbor_order(coords_latlon)
    order = _two_opt(order, coords_latlon)

    # ------------------------------
    # Build required edges for Geoapify
    # ------------------------------
    edges = [(a, b) for a, b in zip(order, order[1:])]
    edges.append((order[-1], order[0]))  # Return to depot

    # ------------------------------
    # Query Geoapify for these edges only
    # ------------------------------
    matrix = matrix_builder(coordinates, edges=edges)

    # ------------------------------
    # Compute drive time
    # ------------------------------
    drive_minutes = sum(
        matrix[(a, b)]["time"] / 60.0
        for (a, b) in edges
        if (a, b) in matrix
    )

    service_minutes = len(requests) * service_minutes_per_stop
    total_minutes = drive_minutes + service_minutes
    feasible = total_minutes <= max_workday_minutes
    reason = None if feasible else f"Estimated {total_minutes:.1f} min exceeds limit"

    # ------------------------------
    # Build final stop order labels (excluding depot idx 0)
    # ------------------------------
    stop_order_labels = [labels[i] for i in order[1:]]

    return DayPlan(
        date=date_label,
        requests=requests,
        stop_order=stop_order_labels,
        drive_minutes=drive_minutes,
        service_minutes=service_minutes,
        feasible=feasible,
        reason=reason,
    )