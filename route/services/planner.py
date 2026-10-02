"""Tie geocoding, one route call, and the fuel plan into an API payload."""

import hashlib

from django.core.cache import cache

from .fuel import FuelPlanError, MPG, MAX_RANGE_MILES, plan_fuel
from .geo import PlaceError, locate_label
from .routing import CORRIDOR_MILES, RoutingError, driving_route, stations_along_route
from .stations import all_stations


class PlanError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def build_plan(start_text, finish_text):
    cache_key = f"plan:v3:{_norm(start_text)}|{_norm(finish_text)}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        start = locate_label(start_text)
        finish = locate_label(finish_text)
    except PlaceError as exc:
        raise PlanError(str(exc), status=400) from exc

    try:
        route = driving_route(start, finish)
    except RoutingError as exc:
        raise PlanError(str(exc), status=502) from exc

    nearby = stations_along_route(
        all_stations(),
        route["coordinates"],
        route["distance_miles"],
    )
    try:
        stops, _total = plan_fuel(nearby, route["distance_miles"])
    except FuelPlanError as exc:
        raise PlanError(str(exc), status=400) from exc

    fuel_stops = [_stop_payload(stop) for stop in stops]
    payload = {
        "start": start,
        "finish": finish,
        "distance_miles": round(route["distance_miles"], 1),
        "duration_minutes": round(route["duration_minutes"], 0),
        "total_fuel_cost_usd": round(sum(stop["cost_usd"] for stop in fuel_stops), 2),
        "assumes_full_tank_at_start": True,
        "mpg": MPG,
        "max_range_miles": MAX_RANGE_MILES,
        "trip_fuel_gallons": round(route["distance_miles"] / MPG, 1),
        "starting_tank_gallons": round(MAX_RANGE_MILES / MPG, 1),
        "purchased_fuel_gallons": round(sum(stop["gallons"] for stop in fuel_stops), 2),
        "fuel_stops": fuel_stops,
        "route": {"type": "LineString", "coordinates": route["coordinates"]},
        "notes": (
            "The vehicle starts with a full tank (50 gallons), so that first tank "
            "is not billed and a trip under 500 miles costs nothing. "
            "total_fuel_cost_usd covers only fuel bought at the stops. Station positions are the city of each truck stop, "
            f"kept when that city is within {CORRIDOR_MILES:.0f} miles of the route. "
            "Where the same stop lists more than one price, the lowest price is used."
        ),
    }
    cache.set(cache_key, payload)
    return payload


def _norm(text):
    cleaned = " ".join((text or "").strip().lower().split())
    return hashlib.sha256(cleaned.encode()).hexdigest()[:24]


def _stop_payload(stop):
    record = stop["station"]
    station = record["station"]
    return {
        "opis_id": station.opis_id,
        "name": station.name,
        "address": station.address,
        "city": station.city,
        "state": station.state,
        "price_per_gallon": float(station.price),
        "mile_along_route": round(stop["mile"], 1),
        "distance_from_route_miles": round(record["offset_miles"], 1),
        "gallons": round(stop["gallons"], 2),
        "cost_usd": round(stop["cost"], 2),
        "lat": station.latitude,
        "lng": station.longitude,
    }
