"""One OSRM driving route, then the stations that sit near that line."""

import math
from collections import defaultdict

import requests
from django.core.cache import cache

from .geo import EARTH_MILES

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{lng1},{lat1};{lng2},{lat2}"
METERS_PER_MILE = 1609.344
MILES_PER_DEGREE = EARTH_MILES * math.pi / 180
CORRIDOR_MILES = 12
# The route is matched at one point per mile, so a point is never more than
# half a mile from the road: small against the 12 mile corridor.
SAMPLE_MILES = 1
CELL_DEGREES = 0.25
# About 100 m. The line sent to the browser drops points closer than this to
# the straight line between their neighbours, which no map zoom can show.
SIMPLIFY_DEGREES = 0.001


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


class StationIndex:
    """Stations grouped by location and bucketed into a lat/lng grid. Build once, query per route."""

    def __init__(self, stations):
        places = defaultdict(list)
        for station in stations:
            places[(station.latitude, station.longitude)].append(station)
        self.grid = defaultdict(list)
        for (lat, lng), group in places.items():
            self.grid[_cell(lat, lng)].append((lat, lng, group))

    def near(self, lat, lng, miles):
        """Every location in the grid cells that could lie within `miles` of the point."""
        row, col = _cell(lat, lng)
        rows = math.ceil(miles / MILES_PER_DEGREE / CELL_DEGREES)
        squeeze = max(math.cos(math.radians(lat)), 0.1)
        cols = math.ceil(miles / (MILES_PER_DEGREE * squeeze) / CELL_DEGREES)
        for r in range(row - rows, row + rows + 1):
            for c in range(col - cols, col + cols + 1):
                yield from self.grid.get((r, c), ())


def stations_along_route(index, coordinates, distance_miles):
    """
    Keep stations whose city is within CORRIDOR_MILES of the polyline, at the
    route mile where they come closest. mile is scaled onto the router's road distance.
    """
    samples, polyline_miles = _resample(coordinates, SAMPLE_MILES)
    if polyline_miles <= 0:
        return []
    scale = distance_miles / polyline_miles

    closest = {}
    for lat, lng, mile in samples:
        for plat, plng, group in index.near(lat, lng, CORRIDOR_MILES):
            dist = _short_distance(lat, lng, plat, plng)
            if dist > CORRIDOR_MILES:
                continue
            best = closest.get((plat, plng))
            if best is None or dist < best[0]:
                closest[(plat, plng)] = (dist, mile, group)

    found = [
        {
            "mile": mile * scale,
            "offset_miles": dist,
            "price": float(station.price),
            "station": station,
        }
        for dist, mile, group in closest.values()
        for station in group
    ]
    found.sort(key=lambda item: (item["mile"], item["price"]))
    return found


def simplify_line(coordinates, tolerance=SIMPLIFY_DEGREES):
    """
    Douglas-Peucker on [lng, lat] pairs: keep only the points that bend the line
    by more than `tolerance` degrees. Coordinates are rounded to about a metre.
    """
    if len(coordinates) < 3:
        return [[round(lng, 5), round(lat, 5)] for lng, lat in coordinates]
    keep = [False] * len(coordinates)
    keep[0] = keep[-1] = True
    pending = [(0, len(coordinates) - 1)]
    while pending:
        first, last = pending.pop()
        far_at = _farthest_point(coordinates, first, last, tolerance * tolerance)
        if far_at is not None:
            keep[far_at] = True
            pending.append((first, far_at))
            pending.append((far_at, last))
    return [
        [round(lng, 5), round(lat, 5)]
        for (lng, lat), kept in zip(coordinates, keep)
        if kept
    ]


def _resample(coordinates, step):
    """Points every `step` miles along the polyline, plus both ends, as (lat, lng, mile)."""
    if len(coordinates) < 2:
        return [], 0.0
    prev_lng, prev_lat = coordinates[0]
    samples = [(prev_lat, prev_lng, 0.0)]
    total = 0.0
    next_at = step
    for lng, lat in coordinates[1:]:
        leg = _short_distance(prev_lat, prev_lng, lat, lng)
        while leg > 0 and total + leg >= next_at:
            fraction = (next_at - total) / leg
            samples.append(
                (
                    prev_lat + (lat - prev_lat) * fraction,
                    prev_lng + (lng - prev_lng) * fraction,
                    next_at,
                )
            )
            next_at += step
        total += leg
        prev_lat, prev_lng = lat, lng
    if samples[-1][2] < total:
        samples.append((prev_lat, prev_lng, total))
    return samples, total


def _short_distance(lat1, lng1, lat2, lng2):
    """Miles between nearby points on a flat-earth approximation; within 0.1% up to a few dozen miles."""
    squeeze = math.cos(math.radians((lat1 + lat2) / 2))
    return MILES_PER_DEGREE * math.hypot(lat2 - lat1, (lng2 - lng1) * squeeze)


def _farthest_point(coordinates, first, last, limit_sq):
    """
    Index of the point between first and last farthest from the segment joining
    them, or None when none is farther than sqrt(limit_sq). This is the hot loop
    of simplify_line, so it compares squared distances and avoids calls.
    """
    ax, ay = coordinates[first]
    bx, by = coordinates[last]
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    far_sq, far_at = limit_sq, None
    for i in range(first + 1, last):
        px, py = coordinates[i]
        if length_sq == 0:
            t = 0.0
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / length_sq
            t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
        ox = px - ax - t * dx
        oy = py - ay - t * dy
        offset_sq = ox * ox + oy * oy
        if offset_sq > far_sq:
            far_sq, far_at = offset_sq, i
    return far_at


def _cell(lat, lng):
    return (math.floor(lat / CELL_DEGREES), math.floor(lng / CELL_DEGREES))
