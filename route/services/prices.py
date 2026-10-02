"""Read the OPIS truck-stop PDF. Columns overlap, so rows are split by x position."""

from collections import defaultdict
from decimal import Decimal

import pdfplumber

from .geo import CityIndex, repair_state

# Character x where each column starts: name, address, city, state, rack, price.
COLUMN_BOUNDS = (84, 137, 191, 245, 300, 356)
COLUMN_NAMES = ("opis", "name", "address", "city", "state", "rack", "price")


def _fields(chars):
    buckets = {name: [] for name in COLUMN_NAMES}
    for char in chars:
        index = 0
        for bound in COLUMN_BOUNDS:
            if char["x0"] >= bound:
                index += 1
            else:
                break
        buckets[COLUMN_NAMES[index]].append(char)
    parsed = {}
    for name, items in buckets.items():
        items.sort(key=lambda item: item["x0"])
        parsed[name] = "".join(item["text"] for item in items)
    return parsed


def iter_price_rows(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            grouped = defaultdict(list)
            for char in page.chars:
                if char["text"].strip():
                    grouped[round(char["top"])].append(char)
            for top in sorted(grouped):
                yield _fields(grouped[top])


def parse_price(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not 0.5 <= value <= 15:
        return None
    return round(value, 3)


def load_stations(pdf_path, cities_csv):
    """Return unique US stations and a small stats dict. Same stop keeps the lowest price."""
    index = CityIndex(cities_csv)
    best = {}
    stats = {
        "rows": 0,
        "skipped_non_us": 0,
        "unmatched_city": 0,
        "bad_price": 0,
    }
    for row in iter_price_rows(pdf_path):
        if not row["opis"].isdigit():
            continue
        stats["rows"] += 1
        price = parse_price(row["price"])
        if price is None:
            stats["bad_price"] += 1
            continue
        repaired = repair_state(row["city"], row["state"])
        if repaired is None:
            stats["skipped_non_us"] += 1
            continue
        city_raw, state = repaired
        hit = index.resolve(city_raw, state)
        if hit is None:
            stats["unmatched_city"] += 1
            continue
        key = (int(row["opis"]), state, hit.key)
        current = best.get(key)
        if current is not None and current["price"] <= price:
            continue
        best[key] = {
            "opis_id": int(row["opis"]),
            "name": row["name"][:80],
            "address": row["address"][:80],
            "city": hit.name,
            "state": state,
            "price": Decimal(f"{price:.3f}"),
            "latitude": hit.latitude,
            "longitude": hit.longitude,
        }
    stats["stations"] = len(best)
    return list(best.values()), stats
