"""US place names, distance, and the city coordinate index."""

import csv
import difflib
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings

EARTH_MILES = 3958.7613

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}

STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}


class PlaceError(Exception):
    pass


@dataclass(frozen=True)
class City:
    name: str
    state: str
    latitude: float
    longitude: float
    key: str


def norm(value):
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def haversine(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlng / 2) ** 2
    )
    return 2 * EARTH_MILES * math.asin(min(1.0, math.sqrt(a)))


def in_usa(lat, lng):
    conus = 24.4 <= lat <= 49.5 and -125.0 <= lng <= -66.5
    alaska = 51.0 <= lat <= 71.6 and -170.0 <= lng <= -129.0
    hawaii = 18.8 <= lat <= 22.3 and -160.3 <= lng <= -154.7
    return conus or alaska or hawaii


# A trailing country ("Austin, TX, USA") or ZIP code ("Dallas, TX 75201") says
# nothing the state does not, so both are dropped before parsing.
COUNTRY_SUFFIX = re.compile(
    r"(?:,\s*|\s+)(?:usa|u\.s\.a\.?|us|u\.s\.?|united states(?: of america)?)\s*$",
    re.IGNORECASE,
)
ZIP_SUFFIX = re.compile(r"\s+\d{5}(?:-\d{4})?\s*$")


def normalize_state(value):
    token = value.strip().lower().replace(".", "")
    if len(token) == 2 and token.upper() in US_STATES:
        return token.upper()
    return STATE_NAMES.get(token)


def parse_place(text):
    """Return ('coords', lat, lng) or ('city', city, state)."""
    raw = (text or "").strip()
    if not raw:
        raise PlaceError("Enter both a start and a finish.")
    coords = re.fullmatch(
        r"(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)",
        raw,
    )
    if coords:
        return ("coords", float(coords.group(1)), float(coords.group(2)))
    raw = COUNTRY_SUFFIX.sub("", raw).strip()
    if "," in raw:
        city, region = raw.rsplit(",", 1)
        region = ZIP_SUFFIX.sub("", region).strip()
        state = normalize_state(region)
        city = city.strip()
        if not city:
            raise PlaceError(f"Could not read location '{text.strip()}'. Use City, ST.")
        if state:
            return ("city", city, state)
        if region:
            # "Toronto, ON" or "Paris, France": say so rather than suggest a US namesake.
            raise PlaceError(
                f"'{region}' is not a US state. Both places must be in the USA, "
                "written as City, ST, for example Dallas, TX."
            )
        return ("name", city, None)
    parts = raw.split()
    if len(parts) >= 2 and normalize_state(parts[-1]):
        return ("city", " ".join(parts[:-1]), normalize_state(parts[-1]))
    return ("name", raw, None)


def repair_state(city, state_raw):
    """Pull a spilled last letter back onto the city. 'MountJack' + 'sVA' -> MountJacks, VA."""
    letters = re.sub(r"[^A-Za-z]", "", state_raw or "")
    if len(letters) == 2 and letters.upper() in US_STATES:
        return city, letters.upper()
    if len(letters) > 2 and letters[-2:].upper() in US_STATES:
        return city + letters[:-2], letters[-2:].upper()
    return None


class CityIndex:
    def __init__(self, path):
        exact = {}
        by_state = {}
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                state = row["STATE_CODE"].strip().upper()
                name = row["CITY"].strip()
                city = City(
                    name=name,
                    state=state,
                    latitude=float(row["LATITUDE"]),
                    longitude=float(row["LONGITUDE"]),
                    key=norm(name),
                )
                exact[(state, city.key)] = city
                by_state.setdefault(state, []).append(city)
        by_name = {}
        for city in exact.values():
            by_name.setdefault(city.key, []).append(city)
        self.exact = exact
        self.by_state = by_state
        self.by_name = by_name

    def lookup(self, city, state):
        key = norm(city)
        if not key:
            return None
        found = self.exact.get((state, key))
        if found:
            return found
        pool = self.by_state.get(state, ())
        if len(key) >= 4:
            prefixed = [item for item in pool if item.key.startswith(key)]
            hit = _unique_shortest(prefixed)
            if hit:
                return hit
        if len(key) >= 5:
            contained = [item for item in pool if key.startswith(item.key) and len(item.key) >= 5]
            hit = _unique_longest(contained)
            if hit:
                return hit
        for alias in self._alias_keys(key):
            found = self.exact.get((state, alias))
            if found:
                return found
        return _closest_city(key, pool)

    def resolve(self, city, state):
        city = re.sub(r"^\d+", "", city or "")
        hit = self.lookup(city, state)
        if hit or len(norm(city)) < 6 or not city[:1].isalpha():
            return hit
        # The address column sometimes spills one letter onto the city.
        return self.lookup(city[1:], state)

    def lookup_name(self, name):
        """Find a city when the user did not type a state. Returns (city, error)."""
        key = norm(name)
        if not key:
            return None, None
        for alias in [key, *self._alias_keys(key)]:
            chosen, error = _choose_matches(name, self.by_name.get(alias, []))
            if chosen or error:
                return chosen, error
        prefixed = [
            (candidate, cities)
            for candidate, cities in self.by_name.items()
            if len(key) >= 5 and candidate.startswith(key) and len(candidate) - len(key) <= 6
        ]
        if len(prefixed) == 1:
            return _choose_matches(prefixed[0][1][0].name, prefixed[0][1])
        return _closest_group(key, self.by_name)

    def _alias_keys(self, key):
        keys = []
        for short, long in (("ST", "SAINT"), ("FT", "FORT"), ("MT", "MOUNT")):
            if key.startswith(short) and not key.startswith(long):
                alias = long + key[len(short):]
                if alias in self.by_name:
                    keys.append(alias)
            if key.startswith(long):
                alias = short + key[len(long):]
                if alias in self.by_name:
                    keys.append(alias)
        return keys


def _choose_matches(typed, matches):
    if not matches:
        return None, None
    if len(matches) == 1:
        return matches[0], None
    shown = ", ".join(
        f"{item.name}, {item.state}"
        for item in sorted(matches, key=lambda item: item.state)[:6]
    )
    return None, (
        f"'{typed}' matches more than one state. Add the state, for example {shown}."
    )


def _closest_city(key, cities):
    grouped = {}
    for city in cities:
        grouped.setdefault(city.key, []).append(city)
    city, _error = _closest_group(key, grouped)
    return city


def _closest_group(key, grouped):
    """Return (matches, error) for the closest city spelling in grouped name -> cities."""
    if len(key) < 4:
        return None, None
    ranked = []
    for candidate, cities in grouped.items():
        if abs(len(candidate) - len(key)) > 3:
            continue
        ratio = difflib.SequenceMatcher(None, key, candidate).ratio()
        if candidate.startswith(key) or key.startswith(candidate):
            ratio = max(ratio, 0.9)
        if ratio >= 0.84:
            ranked.append((ratio, cities))
    if not ranked:
        return None, None
    ranked.sort(key=lambda item: item[0], reverse=True)
    best_ratio, best = ranked[0]
    if best_ratio < 0.86:
        return None, None
    if (
        len(ranked) > 1
        and best[0].key != ranked[1][1][0].key
        and ranked[1][0] >= best_ratio - 0.01
    ):
        options = ", ".join(
            f"{item[1][0].name}, {item[1][0].state}" for item in ranked[:3]
        )
        return None, f"Could not tell which city. Did you mean {options}?"
    return _choose_matches(best[0].name, best)


def _unique_shortest(cities):
    if not cities:
        return None
    cities.sort(key=lambda item: len(item.key))
    best = len(cities[0].key)
    tied = [item for item in cities if len(item.key) == best]
    if len(tied) == 1:
        return tied[0]
    return None


def _unique_longest(cities):
    if not cities:
        return None
    cities.sort(key=lambda item: len(item.key), reverse=True)
    best = len(cities[0].key)
    tied = [item for item in cities if len(item.key) == best]
    if len(tied) == 1:
        return tied[0]
    return None


@lru_cache(maxsize=1)
def city_index():
    return CityIndex(Path(settings.BASE_DIR) / "data" / "us_cities.csv")


def locate_label(text):
    """Resolve a user location to lat, lng, and a display label."""
    kind, a, b = parse_place(text)
    if kind == "coords":
        lat, lng = a, b
        if not in_usa(lat, lng):
            raise PlaceError("Start and finish both need to be inside the USA.")
        return {"label": f"{lat:.4f}, {lng:.4f}", "lat": lat, "lng": lng}
    if kind == "name":
        hit, ambiguity = city_index().lookup_name(a)
        if ambiguity:
            raise PlaceError(ambiguity)
    else:
        hit = city_index().lookup(a, b)
    if hit is None:
        raise PlaceError(
            f"Could not find '{text}' in the USA. Use City, ST, for example New York, NY."
        )
    if not in_usa(hit.latitude, hit.longitude):
        raise PlaceError("Start and finish both need to be inside the USA.")
    return {
        "label": f"{hit.name}, {hit.state}",
        "lat": hit.latitude,
        "lng": hit.longitude,
    }
