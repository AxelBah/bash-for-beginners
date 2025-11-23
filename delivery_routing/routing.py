from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple

from .models import DayPlan, DeliveryRequest, GeocodedLocation


def _build_edges(path: Sequence[str]) -> List[Tuple[str, str]]:
    """Return ordered edges along a closed path (Depot already included)."""

    return list(zip(path[:-1], path[1:]))


class _EdgeFetcher:
    """Cache-aware helper that batches sparse Geoapify matrix requests."""

    def __init__(
        self,
        client,
        locations: Dict[str, GeocodedLocation],
        *,
        mode: str = "drive",
        max_cells: int = 1000,
    ):
        self.client = client
        self.locations = locations
        self.mode = mode
        self.max_cells = max_cells
        self._cache: Dict[Tuple[str, str], float] = {}

    def ensure_times(self, origins: Iterable[str], targets: Iterable[str]):
        origin_ids = list(dict.fromkeys(origins))
        target_ids = list(dict.fromkeys(targets))

        for origin in origin_ids:
            needed = [t for t in target_ids if t != origin and (origin, t) not in self._cache]
            if not needed:
                continue

            start = 0
            while start < len(needed):
                # With a single origin, the cell count equals the number of targets.
                chunk = needed[start : start + self.max_cells]
                durations = self.client.route_matrix(
                    [self.locations[origin]],
                    [self.locations[target] for target in chunk],
                    mode=self.mode,
                )
                for (orig, dest), minutes in durations.items():
                    self._cache[(orig, dest)] = minutes
                start += self.max_cells

    def get_time(self, origin: str, target: str) -> float:
        if origin == target:
            return 0.0
        if (origin, target) not in self._cache:
            self.ensure_times([origin], [target])
        return self._cache[(origin, target)]


def _route_drive_minutes(path: Sequence[str], fetcher: _EdgeFetcher) -> float:
    edges = _build_edges(path)
    fetcher.ensure_times((a for a, _ in edges), (b for _, b in edges))
    return sum(fetcher.get_time(origin, target) for origin, target in edges)


def _nearest_neighbor_route(stops: List[str], fetcher: _EdgeFetcher, depot_id: str) -> Tuple[List[str], float, List[str]]:
    remaining = stops.copy()
    order: List[str] = []
    current = depot_id

    while remaining:
        fetcher.ensure_times([current], remaining)
        next_stop = min(remaining, key=lambda stop: (fetcher.get_time(current, stop), stop))
        order.append(next_stop)
        remaining.remove(next_stop)
        current = next_stop

    path = [depot_id] + order + [depot_id]
    drive_minutes = _route_drive_minutes(path, fetcher)
    return order, drive_minutes, path


def _two_opt(path: List[str], fetcher: _EdgeFetcher) -> Tuple[List[str], float]:
    best = path
    best_cost = _route_drive_minutes(best, fetcher)
    improved = True

    while improved:
        improved = False
        for i in range(1, len(best) - 2):
            for k in range(i + 1, len(best) - 1):
                if k == i + 1:
                    continue  # swapping adjacent edges yields no change
                candidate = best[:i] + best[i : k + 1][::-1] + best[k + 1 :]
                candidate_cost = _route_drive_minutes(candidate, fetcher)
                if candidate_cost + 1e-6 < best_cost:
                    best = candidate
                    best_cost = candidate_cost
                    improved = True
                    break
            if improved:
                break
    return best, best_cost


def build_day_plan(
    date_label,
    deliveries: Iterable[DeliveryRequest],
    geo_locations: Dict[str, GeocodedLocation],
    depot: GeocodedLocation,
    geo_client,
    *,
    service_minutes_per_stop: float = 10.0,
    max_workday_minutes: float = 8 * 60,
) -> DayPlan:
    """Create a :class:`DayPlan` from deliveries scheduled on the same day."""

    requests = list(deliveries)
    if not requests:
        raise ValueError("At least one delivery is required to build a day plan")

    locations: Dict[str, GeocodedLocation] = {depot.identifier: depot}
    for req in requests:
        locations[req.postcode] = geo_locations[req.postcode]

    stop_ids = [req.postcode for req in requests]
    fetcher = _EdgeFetcher(geo_client, locations)

    stop_order, drive_minutes, path = _nearest_neighbor_route(stop_ids, fetcher, depot.identifier)
    improved_path, drive_minutes = _two_opt(path, fetcher)

    service_minutes = len(requests) * service_minutes_per_stop
    total_minutes = drive_minutes + service_minutes
    feasible = total_minutes <= max_workday_minutes
    reason = None if feasible else f"Estimated {total_minutes:.1f} min exceeds workday limit ({max_workday_minutes} min)"

    return DayPlan(
        date=date_label,
        requests=requests,
        stop_order=improved_path[1:-1],
        drive_minutes=drive_minutes,
        service_minutes=service_minutes,
        feasible=feasible,
        reason=reason,
    )
