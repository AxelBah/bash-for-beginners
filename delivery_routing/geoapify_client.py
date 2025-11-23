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
        self.base_url = "https://api.geoapify.com"
        self.headers = {"Content-Type": "application/json"} 

    def geocode_postcodes(self, postcodes):
        results = {}
        for postcode in postcodes:
            if not postcode or not postcode.strip():
                # optionally log skipped rows
                continue

            query_params = {"text": postcode, "apiKey": self.api_key}
            if self.country:
                query_params["filter"] = f"countrycode:{self.country}"

            response = self.session.get(
                "https://api.geoapify.com/v1/geocode/search",
                params=query_params,
                timeout=20
            )

            response.raise_for_status()
            payload = response.json()
            features = payload.get("features", [])

            if not features:
                raise ValueError(f"Geoapify could not geocode postcode '{postcode}'")

            lon, lat = features[0]["geometry"]["coordinates"]
            results[postcode] = GeocodedLocation(
                identifier=postcode,
                longitude=lon,
                latitude=lat,
                raw=features[0],
            )

        return results



    def route_matrix(self, locations, edges):
        """
        Compute only selected origin→destination distances.
        locations: list of GeocodedLocation (index 0 = depot)
        edges: list of (origin, dest) index pairs
        """
        print("EDGE COUNT:", len(edges))
        print("UNIQUE ORIGINS:", len({o for (o, _) in edges}))
        print("UNIQUE DESTS:", len({d for (_, d) in edges}))
        if edges is None or not edges:
            raise ValueError("route_matrix must be called with edges list")

        # Convert input coords once
        geo = [
            {"location": [loc.longitude, loc.latitude]}
            for loc in locations
        ]

        results = {}
        BATCH = 300  # Must be << 1000 to avoid Geoapify limit

        def call(batch):
            origins = sorted({o for (o, _) in batch})
            dests   = sorted({d for (_, d) in batch})

            body = {
                "mode": "drive",
                "sources": [geo[o] for o in origins],
                "targets": [geo[d] for d in dests]
            }

            url = f"{self.base_url}/v1/routematrix"
            params = {"apiKey": self.api_key}

            r = self.session.post(url, params=params, json=body, headers=self.headers)
            if not r.ok:
                print("ERROR:", r.text)
                r.raise_for_status()

            data = r.json()

            # Parse result
            for i, o in enumerate(origins):
                for j, d in enumerate(dests):
                    entry = data["sources_to_targets"][i][j]
                    results[(o, d)] = {
                        "distance": entry.get("distance", 0),
                        "time": entry.get("time", 0),
                    }

        # Batch edges
        batch = []
        for e in edges:
            batch.append(e)
            if len(batch) >= BATCH:
                call(batch)
                batch = []

        if batch:
            call(batch)

        return results
