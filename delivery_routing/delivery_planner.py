from __future__ import annotations

import argparse
import os
from typing import Dict, Iterable, List, Sequence

from .geoapify_client import GeoapifyClient
from .google_sheets_client import fetch_deliveries_from_sheet
from .models import DayPlan, DeliveryRequest, GeocodedLocation
from .routing import build_day_plan


def _load_geo_locations(client: GeoapifyClient, *, depot_address: str, postcodes: Iterable[str]) -> tuple[GeocodedLocation, Dict[str, GeocodedLocation]]:
    depot_location = client.geocode_postcodes([depot_address])[depot_address]
    postcode_locations = client.geocode_postcodes(postcodes)
    return depot_location, postcode_locations


def _haversine_km(a: GeocodedLocation, b: GeocodedLocation) -> float:
    """Calculate haversine distance in kilometers."""

    from math import asin, cos, radians, sin, sqrt  # local import to avoid dependency

    lat1, lon1, lat2, lon2 = map(radians, [a.latitude, a.longitude, b.latitude, b.longitude])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    angle = 2 * asin(sqrt(sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2))
    earth_radius_km = 6371
    return angle * earth_radius_km


def _cluster_by_proximity(
    deliveries: Sequence[DeliveryRequest],
    locations: Dict[str, GeocodedLocation],
    *,
    max_group_km: float = 12.0,
) -> List[List[DeliveryRequest]]:
    """Greedy proximity clustering so nearby postcodes share a delivery day.

    Each cluster is seeded with a single delivery; new deliveries join the first cluster
    where they are within ``max_group_km`` of any member. This keeps geographically-close
    postcodes together without heavy computation.
    """

    clusters: List[List[DeliveryRequest]] = []
    for request in deliveries:
        placed = False
        for cluster in clusters:
            if any(_haversine_km(locations[request.postcode], locations[existing.postcode]) <= max_group_km for existing in cluster):
                cluster.append(request)
                placed = True
                break
        if not placed:
            clusters.append([request])
    return clusters


def plan_routes(
    *,
    sheet_id: str,
    range_name: str,
    service_account_file: str,
    geoapify_key: str,
    depot_address: str,
    service_minutes_per_stop: float = 10.0,
    workday_minutes: float = 8 * 60,
    country: str | None = None,
) -> List[DayPlan]:
    """Build a list of day plans using Google Sheets + Geoapify."""

    deliveries = fetch_deliveries_from_sheet(sheet_id, range_name, service_account_file)
    if not deliveries:
        raise ValueError("No deliveries were found in the provided sheet range")

    client = GeoapifyClient(geoapify_key, country=country)
    depot, postcode_locations = _load_geo_locations(client, depot_address=depot_address, postcodes=grouped_postcodes(deliveries))

    clusters = _cluster_by_proximity(sorted(deliveries, key=lambda d: d.desired_date), postcode_locations)

    plans: List[DayPlan] = []
    for cluster in clusters:
        deadline = min(req.desired_date for req in cluster)
        plan = build_day_plan(
            deadline,
            cluster,
            postcode_locations,
            depot,
            client.route_matrix,
            service_minutes_per_stop=service_minutes_per_stop,
            max_workday_minutes=workday_minutes,
        )
        plans.append(plan)
    return plans


def grouped_postcodes(deliveries: Iterable[DeliveryRequest]) -> List[str]:
    postcodes = {req.postcode for req in deliveries}
    return sorted(postcodes)


def _build_parser():
    parser = argparse.ArgumentParser(description="Create delivery routes from a Google Sheet using Geoapify")
    parser.add_argument("--sheet-id", required=True, help="Google Sheet ID")
    parser.add_argument("--range", dest="range_name", required=True, help="Range to read e.g. Sheet1!A1:D99")
    parser.add_argument("--service-account", required=True, help="Path to Google service account JSON file")
    parser.add_argument("--geoapify-key", default=os.environ.get("GEOAPIFY_API_KEY"), help="Geoapify API key")
    parser.add_argument("--depot", required=True, help="Full address or postcode for the depot/start point")
    parser.add_argument("--country", help="Optional country code to narrow geocoding results (e.g. 'gb')")
    parser.add_argument("--service-minutes", type=float, default=10.0, help="Minutes spent per stop")
    parser.add_argument("--workday-minutes", type=float, default=8 * 60, help="Maximum minutes allowed in a day")
    return parser


def _format_plan(plan: DayPlan) -> str:
    header = f"\n=== {plan.date.isoformat()} ==="
    order = " -> ".join(plan.stop_order)
    summary = (
        f"Stops: {len(plan.requests)}\n"
        f"Route: Depot -> {order} -> Depot\n"
        f"Drive time: {plan.drive_minutes:.1f} min\n"
        f"Service time: {plan.service_minutes:.1f} min\n"
        f"Total: {plan.total_minutes:.1f} min\n"
    )
    if plan.feasible:
        summary += "Feasible within workday."
    else:
        summary += f"Not feasible: {plan.reason}"
    return f"{header}\n{summary}"


def main(argv: List[str] | None = None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.geoapify_key:
        parser.error("--geoapify-key is required (or set GEOAPIFY_API_KEY)")

    plans = plan_routes(
        sheet_id=args.sheet_id,
        range_name=args.range_name,
        service_account_file=args.service_account,
        geoapify_key=args.geoapify_key,
        depot_address=args.depot,
        service_minutes_per_stop=args.service_minutes,
        workday_minutes=args.workday_minutes,
        country=args.country,
    )

    for plan in sorted(plans, key=lambda p: p.date):
        print(_format_plan(plan))


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
