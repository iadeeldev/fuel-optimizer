"""Refueling plan for a fixed tank along an ordered route.

Fuel is tracked in whole miles of range. For each station the search keeps the
best way to leave it with every possible fuel level, so the result is the true
minimum of fuel cost plus a fixed charge per stop. A charge of 0 gives the
cheapest plan; a few dollars trades a little fuel money for far fewer stops.
"""

import math

MAX_RANGE_MILES = 500
MPG = 10


class FuelPlanError(Exception):
    pass


def plan_fuel(stations, dest_miles, max_range=MAX_RANGE_MILES, mpg=MPG, stop_penalty=0.0):
    """
    stations: dicts with mile (from the start) and price (dollars per gallon).
    The vehicle leaves mile 0 with a full tank. Returns (stops, money spent),
    where each stop has mile, price, gallons, cost and the station dict.
    """
    if dest_miles < 0:
        raise FuelPlanError("Route distance is not usable.")
    # A full tank already finishes the trip, so no money is spent.
    if dest_miles <= max_range + 1e-6:
        return [], 0.0

    dest = round(dest_miles)
    points = _cheapest_per_mile(stations, dest_miles)
    choices, end_fuel = _search(points, dest, max_range, mpg, stop_penalty)
    plan = _chosen_stops(points, choices, end_fuel, dest)
    return _size_purchases(plan, dest, dest_miles, max_range, mpg)


def _cheapest_per_mile(stations, dest_miles):
    """One station per whole mile: a dearer stop at the same spot is never worth it."""
    best = {}
    for station in stations:
        if not 1e-3 < station["mile"] < dest_miles - 1e-3:
            continue
        mile = round(station["mile"])
        current = best.get(mile)
        if current is None or station["price"] < current["price"]:
            best[mile] = station
    return sorted(best.items())


def _search(points, dest, tank, mpg, penalty):
    """Walk the stations in order. Returns each station's buy choices and the fuel left at the finish."""
    arrive = [math.inf] * (tank + 1)
    arrive[tank] = 0.0
    pos = 0
    choices = []
    for mile, station in points:
        arrive = _drive(arrive, mile - pos)
        leave, came_from = _buy(arrive, station["price"] / mpg, penalty)
        choices.append(came_from)
        arrive = leave
        pos = mile
    final = _drive(arrive, dest - pos)
    end_fuel = min(range(len(final)), key=final.__getitem__)
    return choices, end_fuel


def _drive(levels, miles):
    """Fuel levels after driving `miles`; levels that cannot cover the distance drop out."""
    if miles > len(levels) - 1:
        raise _gap_error(len(levels) - 1)
    shifted = levels[miles:] + [math.inf] * miles
    if min(shifted) == math.inf:
        raise _gap_error(len(levels) - 1)
    return shifted


def _buy(arrive, dollars_per_mile, penalty):
    """
    Best cost of leaving with each fuel level, and the arrival level it came from.
    Buying from f up to g costs (g - f) * price plus the stop charge, so a running
    minimum of arrive[f] - f * price covers every f below g in one pass.
    """
    leave = list(arrive)
    came_from = list(range(len(arrive)))
    low, low_at = math.inf, -1
    for level, cost in enumerate(arrive):
        bought = low + level * dollars_per_mile + penalty
        if bought < leave[level] - 1e-9:
            leave[level] = bought
            came_from[level] = low_at
        value = cost - level * dollars_per_mile
        if value < low:
            low, low_at = value, level
    return leave, came_from


def _chosen_stops(points, choices, end_fuel, dest):
    """Trace the winning plan back from the finish: (whole mile, station, fuel on leaving) per stop."""
    plan = []
    fuel = end_fuel
    next_mile = dest
    for (mile, station), came_from in zip(reversed(points), reversed(choices)):
        leave = fuel + next_mile - mile
        if leave > came_from[leave]:
            plan.append((mile, station, leave))
        fuel = came_from[leave]
        next_mile = mile
    plan.reverse()
    return plan


def _size_purchases(plan, dest, dest_miles, tank, mpg):
    """
    The search rounds stations to whole miles, which can leave the tank a fraction
    of a mile short of a stop or over full. Replay the chosen stops on the true
    miles instead: at each stop buy enough to reach the next one with the fuel the
    search planned to arrive with, never past a full tank.
    """
    stops = []
    fuel = float(tank)
    here = 0.0
    ahead = [(mile, station["mile"]) for mile, station, _leave in plan[1:]] + [(dest, dest_miles)]
    for (mile, station, leave), (next_mile, next_true) in zip(plan, ahead):
        fuel -= station["mile"] - here
        here = station["mile"]
        if fuel < -1e-9:
            raise _gap_error(tank)
        arrive_next = leave - (next_mile - mile)
        target = min(arrive_next + next_true - here, float(tank))
        need = target - fuel
        if need <= 1e-9:
            continue
        fuel += need
        gallons = need / mpg
        stops.append(
            {
                "mile": here,
                "price": station["price"],
                "gallons": gallons,
                "cost": gallons * station["price"],
                "station": station,
            }
        )
    if fuel - (dest_miles - here) < -1e-9:
        raise _gap_error(tank)
    return stops, sum(stop["cost"] for stop in stops)


def _gap_error(tank):
    return FuelPlanError(
        f"No fuel plan keeps the vehicle inside its {tank} mile range. "
        f"There is a stretch longer than {tank} miles without a station."
    )
