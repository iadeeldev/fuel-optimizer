"""One OSRM driving route, then the stations that sit near that line."""

from collections import defaultdict

import requests
from django.core.cache import cache

from .geo import haversine

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{lng1},{lat1};{lng2},{lat2}"
METERS_PER_MILE = 1609.344
CORRIDOR_MILES = 12
SAMPLE_MILES = 2
CELL_DEGREES = 1.0


class RoutingError(Exception):
    pass


def driving_route(start, finish):
    """Return distance_miles, duration_minutes, and GeoJSON coordinates. One HTTP call."""
    key = (
        "osrm:v1:"
        f"{start['lat']:.3f}:{start['lng']:.3f}:"
        f"{finish['lat']:.3f}:{finish['lng']:.3f}"
    )
    cached = cache.get(key)
    if cached is not None:
        return cached

    url = OSRM_URL.format(
        lng1=start["lng"],
        lat1=start["lat"],
        lng2=finish["lng"],
        lat2=finish["lat"],
    )
    try:
        response = requests.get(
            url,
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
            timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RoutingError("The routing service did not respond. Try again.") from exc

    routes = payload.get("routes") or []
    if payload.get("code") != "Ok" or not routes:
        raise RoutingError("No driving route was found between those points.")

    route = routes[0]
    geometry = route.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if len(coordinates) < 2:
        raise RoutingError("No driving route was found between those points.")

    result = {
        "distance_miles": route["distance"] / METERS_PER_MILE,
        "duration_minutes": route["duration"] / 60.0,
        "coordinates": coordinates,
    }
    cache.set(key, result)
    return result


def _polyline_miles(coordinates):
    """Points about every two miles, so a long straight leg still has samples."""
    points = []
    total = 0.0
    prev_lng, prev_lat = coordinates[0]
    points.append((prev_lat, prev_lng, 0.0))
    for lng, lat in coordinates[1:]:
        dist = haversine(prev_lat, prev_lng, lat, lng)
        if dist > SAMPLE_MILES:
            steps = int(dist // SAMPLE_MILES)
            for step in range(1, steps + 1):
                fraction = (step * SAMPLE_MILES) / dist
                if fraction >= 1:
                    break
                points.append(
                    (
                        prev_lat + (lat - prev_lat) * fraction,
                        prev_lng + (lng - prev_lng) * fraction,
                        total + step * SAMPLE_MILES,
                    )
                )
        total += dist
        points.append((lat, lng, total))
        prev_lat, prev_lng = lat, lng
    return points, total


def stations_along_route(stations, coordinates, distance_miles):
    """
    Keep stations whose city is within CORRIDOR_MILES of the polyline.
    mile is scaled onto the router's road distance.
    """
    points, polyline_miles = _polyline_miles(coordinates)
    if polyline_miles <= 0:
        return []
    scale = distance_miles / polyline_miles

    grid = defaultdict(list)
    for index in range(len(points)):
        lat, lng, _mile = points[index]
        grid[(int(lat / CELL_DEGREES), int(lng / CELL_DEGREES))].append(index)

    found = []
    for station in stations:
        lat = station.latitude
        lng = station.longitude
        cell = (int(lat / CELL_DEGREES), int(lng / CELL_DEGREES))
        best = None
        best_mile = None
        for dlat in (-1, 0, 1):
            for dlng in (-1, 0, 1):
                for index in grid.get((cell[0] + dlat, cell[1] + dlng), ()):
                    plat, plng, mile = points[index]
                    dist = haversine(lat, lng, plat, plng)
                    if best is None or dist < best:
                        best = dist
                        best_mile = mile
        if best is None or best > CORRIDOR_MILES:
            continue
        found.append(
            {
                "mile": best_mile * scale,
                "offset_miles": best,
                "price": float(station.price),
                "station": station,
            }
        )
    found.sort(key=lambda item: (item["mile"], item["price"]))
    return found
