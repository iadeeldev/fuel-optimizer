# Fuel route API

Django 6.1 API that plans a USA driving route, picks cost-effective fuel stops
for a vehicle with a 500 mile range and 10 mpg, and returns the route line plus
the total fuel cost.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set DJANGO_SECRET_KEY
python manage.py migrate
python manage.py createcachetable
python manage.py import_stations
python manage.py runserver
```

Open http://127.0.0.1:8000/ for the map.

## API

```
GET /api/route/?start=Chicago,%20IL&finish=Dallas,%20TX
GET /api/route/?start=Chicago,%20IL&finish=Dallas,%20TX&plan=fewer_stops
```

Every response carries two fuel plans under `plans`:

- `cheapest` (default): the lowest fuel bill.
- `fewer_stops`: counts `FUEL_STOP_PENALTY_USD` (default $5) per stop for driver
  time, so it stops far less for a slightly higher bill.

`plan` picks which one fills `fuel_stops` and `total_fuel_cost_usd`, and
`plan_comparison` sums up the difference. Both come from the same single route
call, so switching plans costs nothing. The map page has a toggle for the two.

Swagger UI: http://127.0.0.1:8000/api/docs/ (OpenAPI file at `/api/schema/`,
which Postman can import). The response includes `map_url`, a link that opens
the route and fuel stops on a map.

### Fuel cost

The vehicle starts with a full tank (50 gallons).

- `total_fuel_cost_usd`: money spent at the stops. A trip under 500 miles spends nothing.
- `trip_fuel_cost_usd`: cost of all fuel the trip burns, the stops plus the
  starting fuel used, valued at `starting_tank_price_per_gallon` (the average
  price of the stations along the route).

### Caching, limits and compression

- Routing uses one OSRM call per distinct trip. Results are kept for 24 hours in
  a database cache that every server process shares and that survives restarts.
- Each client may call `/api/route/` `ROUTE_RATE_LIMIT` times (default
  `30/minute`); beyond that it gets `429`. This keeps us inside the free OSRM
  server's usage policy.
- Route replies are gzipped for clients that accept it (about 3x smaller).
  Compression is applied to that endpoint only, not site-wide (BREACH).

Station coordinates are the city of each truck stop. The same stop keeps its
lowest listed price.
