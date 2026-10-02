from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

from route.models import FuelStation
from route.services.fuel import FuelPlanError, plan_fuel
from route.services.geo import CityIndex, PlaceError, haversine, locate_label, repair_state
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
