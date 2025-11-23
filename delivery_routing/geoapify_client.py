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

    def route_matrix(self, coordinates: Sequence[GeocodedLocation], *, mode: str = "drive") -> List[List[float]]:
        """Create a square matrix of travel times in minutes between coordinates."""

        locations = [
            {
                "location": [location.longitude, location.latitude],
                "id": location.identifier,
            }
            for location in coordinates
        ]
        body = {
            "mode": mode,
            "sources": list(range(len(locations))),
            "targets": list(range(len(locations))),
            "locations": locations,
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

        # durations are in seconds in the same order as submitted locations
        return [
            [float(cell["time"] / 60.0) for cell in row]
            for row in durations
        ]
