import math
import random
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

from route.models import FuelStation
from route.services.fuel import FuelPlanError, plan_fuel
from route.services.geo import CityIndex, PlaceError, haversine, locate_label, repair_state
from route.services.routing import (
    CORRIDOR_MILES,
    MILES_PER_DEGREE,
    StationIndex,
    _resample,
    simplify_line,
    stations_along_route,
)
from route.services.stations import clear_station_cache


class FuelPlanTests(TestCase):
    def test_short_trip_uses_the_starting_tank(self):
        stops, cost = plan_fuel([{"mile": 80, "price": 4.5}], 120)
        self.assertEqual(stops, [])
        self.assertEqual(cost, 0)

    def test_buys_only_enough_to_finish(self):
        stops, cost = plan_fuel([{"mile": 400, "price": 3.2}], 700)
        self.assertEqual(len(stops), 1)
        self.assertAlmostEqual(stops[0]["gallons"], 20)
        self.assertAlmostEqual(cost, 64)

    def test_partial_fill_reaches_a_cheaper_station(self):
        stops, cost = plan_fuel(
            [
                {"mile": 400, "price": 4.0},
                {"mile": 700, "price": 2.0},
            ],
            900,
        )
        self.assertEqual(len(stops), 2)
        self.assertAlmostEqual(stops[0]["gallons"], 20)
        self.assertAlmostEqual(stops[0]["cost"], 80)
        self.assertAlmostEqual(stops[1]["gallons"], 20)
        self.assertAlmostEqual(stops[1]["cost"], 40)
        self.assertAlmostEqual(cost, 120)

    def test_fills_up_when_the_next_stretch_is_expensive(self):
        stops, cost = plan_fuel(
            [
                {"mile": 400, "price": 3.0},
                {"mile": 900, "price": 4.0},
            ],
            1300,
        )
        self.assertEqual(len(stops), 2)
        self.assertAlmostEqual(stops[0]["gallons"], 40)
        self.assertAlmostEqual(stops[0]["cost"], 120)
        self.assertAlmostEqual(stops[1]["gallons"], 40)
        self.assertAlmostEqual(stops[1]["cost"], 160)
        self.assertAlmostEqual(cost, 280)

    def test_gap_over_500_miles_is_rejected(self):
        with self.assertRaises(FuelPlanError):
            plan_fuel([{"mile": 600, "price": 3}], 800)

    def test_gap_is_rejected_with_a_stop_charge_too(self):
        with self.assertRaises(FuelPlanError):
            plan_fuel([{"mile": 400, "price": 3}, {"mile": 950, "price": 3}], 1200, stop_penalty=5)

    def test_matches_an_exhaustive_search(self):
        rng = random.Random(1)
        for _ in range(200):
            dest = rng.randint(501, 2000)
            stations = _random_stations(rng, dest)
            best = _exhaustive_cost(stations, dest)
            if best is None:
                with self.assertRaises(FuelPlanError):
                    plan_fuel(stations, dest)
                continue
            _stops, cost = plan_fuel(stations, dest)
            self.assertAlmostEqual(cost, best, places=6)

    def test_case_the_old_greedy_overpaid(self):
        # The previous planner paid $329.76 here.
        stations = [
            {"mile": mile, "price": price}
            for mile, price in [
                (158, 4.13), (207, 3.15), (219, 3.71), (290, 4.48), (307, 4.4),
                (316, 3.01), (355, 3.94), (368, 3.74), (602, 4.12), (626, 3.31),
                (655, 3.15), (672, 4.03), (1027, 3.73), (1043, 4.2), (1054, 4.27),
                (1233, 3.22), (1363, 3.86), (1453, 2.88),
            ]
        ]
        _stops, cost = plan_fuel(stations, 1511)
        self.assertAlmostEqual(cost, 318.539, places=3)

    def test_stop_charge_trades_a_little_money_for_fewer_stops(self):
        stations = [
            {"mile": 200, "price": 3.4},
            {"mile": 500, "price": 3.3},
            {"mile": 550, "price": 3.2},
        ]
        cheap_stops, cheap_cost = plan_fuel(stations, 800)
        few_stops, few_cost = plan_fuel(stations, 800, stop_penalty=5)
        self.assertEqual([stop["mile"] for stop in cheap_stops], [500, 550])
        self.assertAlmostEqual(cheap_cost, 96.5)
        self.assertEqual([stop["mile"] for stop in few_stops], [500])
        self.assertAlmostEqual(few_stops[0]["gallons"], 30)
        self.assertAlmostEqual(few_cost, 99.0)

    def test_stop_charge_never_adds_stops_or_saves_money(self):
        rng = random.Random(2)
        for _ in range(200):
            dest = rng.randint(501, 2000)
            stations = _random_stations(rng, dest)
            try:
                cheap_stops, cheap_cost = plan_fuel(stations, dest)
            except FuelPlanError:
                continue
            few_stops, few_cost = plan_fuel(stations, dest, stop_penalty=5)
            self.assertLessEqual(len(few_stops), len(cheap_stops))
            self.assertGreaterEqual(few_cost, cheap_cost - 1e-6)


class RouteGeometryTests(TestCase):
    def test_resample_puts_a_point_every_mile(self):
        ten_miles_north = 40 + 10 / MILES_PER_DEGREE
        samples, total = _resample([[-98, 40], [-98, ten_miles_north]], 1)
        self.assertAlmostEqual(total, 10, places=6)
        self.assertEqual(len(samples), 11)
        self.assertAlmostEqual(samples[5][2], 5)
        self.assertAlmostEqual(samples[-1][0], ten_miles_north)

    def test_resample_needs_two_points(self):
        self.assertEqual(_resample([[-98, 40]], 1), ([], 0.0))

    def test_simplify_collapses_a_straight_line(self):
        line = [[-100 + i * 0.01, 40 + i * 0.01] for i in range(101)]
        self.assertEqual(simplify_line(line), [[-100, 40], [-99, 41]])

    def test_simplify_keeps_a_corner(self):
        line = [[-100, 40], [-99.5, 40], [-99, 40], [-99, 40.5], [-99, 41]]
        self.assertEqual(simplify_line(line), [[-100, 40], [-99, 40], [-99, 41]])

    def test_simplify_rounds_a_short_line(self):
        self.assertEqual(simplify_line([[-98.1234567, 40.7654321]]), [[-98.12346, 40.76543]])


class StationMatchTests(TestCase):
    def test_keeps_a_nearby_station_and_drops_a_far_one(self):
        near = _station(1, 40.1, -99)  # about 7 miles north of the route
        twin = _station(2, 40.1, -99)  # same city, so same place
        far = _station(3, 40.5, -99)  # about 35 miles north
        found = stations_along_route(
            StationIndex([near, twin, far]),
            [[-100, 40], [-98, 40]],
            106,
        )
        self.assertEqual({item["station"].id for item in found}, {1, 2})
        self.assertAlmostEqual(found[0]["offset_miles"], 0.1 * MILES_PER_DEGREE, delta=0.5)
        self.assertAlmostEqual(found[0]["mile"], 53, delta=1)

    def test_no_route_finds_nothing(self):
        self.assertEqual(stations_along_route(StationIndex([_station(1, 40, -99)]), [], 0), [])

    def test_matches_a_brute_force_search(self):
        rng = random.Random(4)
        route = [[-100 + i * 0.05, 40 + 0.3 * math.sin(i / 5)] for i in range(80)]
        stations = [
            _station(i, rng.uniform(39.3, 40.9), rng.uniform(-100.3, -95.7))
            for i in range(400)
        ]
        found = {
            item["station"].id: item["offset_miles"]
            for item in stations_along_route(StationIndex(stations), route, 220)
        }
        dense, _total = _resample(route, 0.05)
        for station in stations:
            offset = min(
                haversine(station.latitude, station.longitude, lat, lng)
                for lat, lng, _mile in dense
            )
            if abs(offset - CORRIDOR_MILES) < 0.6:
                continue  # sampling can tip a station right on the edge either way
            self.assertEqual(station.id in found, offset < CORRIDOR_MILES, station)
            if station.id in found:
                self.assertAlmostEqual(found[station.id], offset, delta=0.6)


def _station(station_id, lat, lng, price="3.000"):
    return SimpleNamespace(id=station_id, latitude=lat, longitude=lng, price=Decimal(price))


def _random_stations(rng, dest):
    miles = rng.sample(range(1, dest), rng.randint(3, 20))
    return [{"mile": mile, "price": round(rng.uniform(2.8, 4.5), 2)} for mile in miles]


def _exhaustive_cost(stations, dest, tank=500, mpg=10):
    """Cheapest cost by trying every fuel level at every station, one mile of fuel at a time."""
    best = {tank: 0.0}
    pos = 0
    for station in sorted(stations, key=lambda s: s["mile"]) + [{"mile": dest, "price": None}]:
        leg = station["mile"] - pos
        arrived = {}
        for fuel, cost in best.items():
            if fuel >= leg:
                arrived[fuel - leg] = min(arrived.get(fuel - leg, math.inf), cost)
        if not arrived:
            return None
        if station["price"] is not None:
            levels = [arrived.get(fuel, math.inf) for fuel in range(tank + 1)]
            for fuel in range(1, tank + 1):
                levels[fuel] = min(levels[fuel], levels[fuel - 1] + station["price"] / mpg)
            arrived = {fuel: cost for fuel, cost in enumerate(levels) if cost < math.inf}
        best = arrived
        pos = station["mile"]
    return min(best.values())


class CityMatchTests(TestCase):
    def test_spilled_letter_and_truncated_name(self):
        city, state = repair_state("MountJack", "sVA")
        self.assertEqual((city, state), ("MountJacks", "VA"))
        index = CityIndex(settings.BASE_DIR / "data" / "us_cities.csv")
        hit = index.resolve(city, state)
        self.assertEqual(hit.name, "Mount Jackson")
        self.assertAlmostEqual(hit.latitude, 38.77, places=1)

    def test_council_bluffs_spill(self):
        city, state = repair_state("CouncilBluf", "fIA")
        index = CityIndex(settings.BASE_DIR / "data" / "us_cities.csv")
        hit = index.resolve(city, state)
        self.assertEqual(hit.name, "Council Bluffs")
        self.assertEqual(hit.state, "IA")

    def test_canada_is_dropped(self):
        self.assertIsNone(repair_state("GrandePrai", "rAB"))

    def test_new_york_without_a_state(self):
        hit = locate_label("New York")
        self.assertEqual(hit["label"], "New York, NY")
        self.assertAlmostEqual(hit["lat"], 40.75, places=1)

    def test_close_spelling_finds_the_city(self):
        self.assertEqual(locate_label("Alameda")["label"], "Alameda, CA")
        self.assertEqual(locate_label("Alamda")["label"], "Alameda, CA")
        self.assertEqual(locate_label("los angelos")["label"], "Los Angeles, CA")
        self.assertEqual(locate_label("Chicgo")["label"], "Chicago, IL")

    def test_ambiguous_city_asks_for_a_state(self):
        with self.assertRaises(PlaceError):
            locate_label("Dallas")


class RouteApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        FuelStation.objects.create(
            opis_id=1,
            name="CHEAP STOP",
            address="I-70",
            city="Testville",
            state="KS",
            price=Decimal("3.000"),
            latitude=40.08,
            longitude=-98,
        )

    def setUp(self):
        cache.clear()
        clear_station_cache()

    def _osrm(self, miles, lng1, lat1, lng2, lat2):
        return {
            "code": "Ok",
            "routes": [
                {
                    "distance": miles * 1609.344,
                    "duration": miles * 60,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lng1, lat1], [lng2, lat2]],
                    },
                }
            ],
        }

    @patch("route.services.routing.requests.get")
    def test_plan_returns_a_stop_and_calls_the_router_once(self, get):
        miles = haversine(40, -104, 40, -89)
        payload = self._osrm(miles, -104, 40, -89, 40)
        get.return_value.json.return_value = payload
        get.return_value.raise_for_status.return_value = None

        first = self.client.get("/api/route/", {"start": "Chicago, IL", "finish": "Dallas, TX"})
        second = self.client.get("/api/route/", {"start": "Chicago, IL", "finish": "Dallas, TX"})
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertGreater(body["distance_miles"], 500)
        self.assertGreater(body["total_fuel_cost_usd"], 0)
        self.assertGreaterEqual(len(body["fuel_stops"]), 1)
        self.assertEqual(body["fuel_stops"][0]["city"], "Testville")
        self.assertIn("/?start=", body["map_url"])
        self.assertGreater(body["trip_fuel_gallons"], body["starting_tank_gallons"])
        self.assertGreater(body["purchased_fuel_gallons"], 0)
        self.assertEqual(body["route"]["type"], "LineString")
        self.assertEqual(second.json()["total_fuel_cost_usd"], body["total_fuel_cost_usd"])
        self.assertEqual(get.call_count, 1)
        self.assertEqual(body["plan"], "cheapest")
        self.assertEqual(set(body["plans"]), {"cheapest", "fewer_stops"})
        self.assertEqual(body["fuel_stops"], body["plans"]["cheapest"]["fuel_stops"])
        self.assertIn("plan=cheapest", body["map_url"])
        self.assertTrue(body["plan_comparison"])

    @patch("route.services.routing.requests.get")
    def test_fewer_stops_plan_reuses_the_same_route_call(self, get):
        miles = haversine(40, -104, 40, -89)
        get.return_value.json.return_value = self._osrm(miles, -104, 40, -89, 40)
        get.return_value.raise_for_status.return_value = None
        trip = {"start": "Chicago, IL", "finish": "Dallas, TX"}

        self.client.get("/api/route/", trip)
        response = self.client.get("/api/route/", {**trip, "plan": "fewer_stops"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["plan"], "fewer_stops")
        self.assertEqual(body["fuel_stops"], body["plans"]["fewer_stops"]["fuel_stops"])
        self.assertEqual(
            body["total_fuel_cost_usd"],
            body["plans"]["fewer_stops"]["total_fuel_cost_usd"],
        )
        self.assertIn("plan=fewer_stops", body["map_url"])
        self.assertEqual(get.call_count, 1)

    @patch("route.services.routing.requests.get")
    def test_unknown_plan_is_rejected_before_routing(self, get):
        response = self.client.get(
            "/api/route/",
            {"start": "Chicago, IL", "finish": "Dallas, TX", "plan": "fastest"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("plan", response.json()["error"])
        get.assert_not_called()

    @patch("route.services.routing.requests.get")
    def test_short_trip_costs_nothing(self, get):
        get.return_value.json.return_value = self._osrm(180, -71.06, 42.36, -74.0, 40.71)
        get.return_value.raise_for_status.return_value = None
        response = self.client.get(
            "/api/route/",
            {"start": "Boston, MA", "finish": "New York, NY"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total_fuel_cost_usd"], 0)
        self.assertEqual(body["fuel_stops"], [])

    @patch("route.services.routing.requests.get")
    def test_unreachable_stretch_is_an_error(self, get):
        get.return_value.json.return_value = self._osrm(700, -69, 47, -56, 47)
        get.return_value.raise_for_status.return_value = None
        response = self.client.get(
            "/api/route/",
            {"start": "Seattle, WA", "finish": "Miami, FL"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("500", response.json()["error"])

    def test_missing_place_does_not_need_the_router(self):
        response = self.client.get("/api/route/", {"start": "Chicago, IL"})
        self.assertEqual(response.status_code, 400)

    def test_map_page_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fuel route")
        self.assertContains(response, 'data-plan="fewer_stops"')
        self.assertContains(response, 'data-initial="cheapest"')

    def test_map_page_opens_on_the_linked_plan(self):
        response = self.client.get("/", {"plan": "fewer_stops"})
        self.assertContains(response, 'data-initial="fewer_stops"')

    def test_map_page_ignores_an_unknown_plan(self):
        response = self.client.get("/", {"plan": "<script>"})
        self.assertContains(response, 'data-initial="cheapest"')
