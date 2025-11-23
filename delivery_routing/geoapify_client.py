from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

import requests

from .models import GeocodedLocation


class GeoapifyClient:
    """Thin wrapper around Geoapify's APIs for geocoding and matrices."""

    def __init__(self, api_key: str, session: requests.Session | None = None, *, country: str | None = None):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.country = country

    def geocode_postcodes(self, postcodes: Iterable[str]) -> Dict[str, GeocodedLocation]:
        """Turn postcodes into latitude/longitude pairs using Geoapify."""

        results: Dict[str, GeocodedLocation] = {}
        for postcode in postcodes:
            query_params = {"text": postcode, "format": "json", "apiKey": self.api_key}
            if self.country:
                query_params["filter"] = f"countrycode:{self.country}"
            response = self.session.get("https://api.geoapify.com/v1/geocode/search", params=query_params, timeout=20)
            response.raise_for_status()
            payload = response.json()
            features = payload.get("features", [])
            if not features:
                raise ValueError(f"Geoapify could not geocode postcode '{postcode}'")

            geometry = features[0]["geometry"]["coordinates"]
            results[postcode] = GeocodedLocation(
                identifier=postcode,
                longitude=geometry[0],
                latitude=geometry[1],
                raw=features[0],
            )
        return results

    def route_matrix(
        self,
        origins: Sequence[GeocodedLocation],
        targets: Sequence[GeocodedLocation],
        *,
        mode: str = "drive",
    ) -> Dict[tuple[str, str], float]:
        """Request only the origin→target cells needed for routing.

        Geoapify limits each matrix to ``sources * targets <= 1000`` cells. Origins
        and targets are deduplicated (while preserving order) so callers can submit
        sparse batches without inflating the matrix size. The return value is a
        mapping ``(origin_id, target_id) -> minutes`` for the requested cells.
        """

        def _dedupe(sequence: Sequence[GeocodedLocation]):
            seen = set()
            ordered: List[GeocodedLocation] = []
            for item in sequence:
                if item.identifier in seen:
                    continue
                seen.add(item.identifier)
                ordered.append(item)
            return ordered

        unique_origins = _dedupe(origins)
        unique_targets = _dedupe(targets)

        # Build a combined location list so source/target indices line up correctly.
        index_by_id: Dict[str, int] = {}
        locations: List[GeocodedLocation] = []
        for loc in unique_origins + unique_targets:
            if loc.identifier in index_by_id:
                continue
            index_by_id[loc.identifier] = len(locations)
            locations.append(loc)

        sources = [index_by_id[loc.identifier] for loc in unique_origins]
        target_indices = [index_by_id[loc.identifier] for loc in unique_targets]

        if sources and target_indices and len(sources) * len(target_indices) > 1000:
            raise ValueError("Route matrix request exceeds Geoapify cell limit (1000)")

        body = {
            "mode": mode,
            "sources": sources,
            "targets": target_indices,
            "locations": [
                {
                    "location": [loc.longitude, loc.latitude],
                    "id": loc.identifier,
                }
                for loc in locations
            ],
        }
        response = self.session.post(
            "https://api.geoapify.com/v1/routematrix",
            params={"apiKey": self.api_key},
            json=body,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        durations = payload.get("sources_to_targets", [])
        if not durations:
            raise ValueError("Geoapify returned an empty matrix response")

        times: Dict[tuple[str, str], float] = {}
        for origin_idx, row in enumerate(durations):
            origin_id = unique_origins[origin_idx].identifier
            for target_idx, cell in enumerate(row):
                target_id = unique_targets[target_idx].identifier
                times[(origin_id, target_id)] = float(cell["time"] / 60.0)

        return times
