"""Cheapest refueling plan for a fixed tank, along an ordered route."""

MAX_RANGE_MILES = 500
MPG = 10


class FuelPlanError(Exception):
    pass


def plan_fuel(stations, dest_miles, max_range=MAX_RANGE_MILES, mpg=MPG):
    """
    stations: dicts with mile (from the start) and price (dollars per gallon).
    The vehicle leaves mile 0 with a full tank. Buy the cheapest fuel that
    still reaches the destination without running dry. A purchase is only as
    large as the tank, and only as large as needed to reach a cheaper station
    or the finish when one is inside a full tank.
    """
    if dest_miles < 0:
        raise FuelPlanError("Route distance is not usable.")
    # A full tank already finishes the trip, so no money is spent.
    if dest_miles <= max_range + 1e-6:
        return [], 0.0

    points = sorted(
        (s for s in stations if 1e-3 < s["mile"] < dest_miles - 1e-3),
        key=lambda s: (s["mile"], s["price"]),
    )
    pos = 0.0
    fuel = float(max_range)
    stops = []
    total = 0.0
    guard = 0
    limit = len(points) + 2

    while pos < dest_miles - 1e-3:
        guard += 1
        if guard > limit:
            raise FuelPlanError(
                "No fuel plan keeps the vehicle inside its 500 mile range."
            )
        reach = pos + fuel
        if reach >= dest_miles - 1e-3:
            break
        choices = [
            s for s in points if pos + 1e-3 < s["mile"] <= reach + 1e-3
        ]
        if not choices:
            raise FuelPlanError(
                "No fuel plan keeps the vehicle inside its 500 mile range. "
                "There is a stretch longer than 500 miles without a station."
            )
        cheapest = min(s["price"] for s in choices)
        pool = [s for s in choices if s["price"] <= cheapest + 1e-9]
        station = max(pool, key=lambda s: s["mile"])

        fuel -= station["mile"] - pos
        pos = station["mile"]

        window = pos + max_range
        cheaper_ahead = [
            s
            for s in points
            if pos + 1e-3 < s["mile"] <= window + 1e-3 and s["price"] < station["price"] - 1e-9
        ]
        if cheaper_ahead:
            target = min(cheaper_ahead, key=lambda s: (s["price"], s["mile"]))
            need = target["mile"] - pos - fuel
        elif dest_miles <= window + 1e-3:
            need = dest_miles - pos - fuel
        else:
            need = max_range - fuel

        need = max(0.0, min(need, max_range - fuel))
        if need <= 1e-6:
            continue
        gallons = need / mpg
        cost = gallons * station["price"]
        fuel += need
        total += cost
        stops.append(
            {
                "mile": pos,
                "price": station["price"],
                "gallons": gallons,
                "cost": cost,
                "station": station,
            }
        )

    if pos + fuel < dest_miles - 1e-2:
        raise FuelPlanError(
            "No fuel plan keeps the vehicle inside its 500 mile range."
        )
    return stops, total
