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
python manage.py import_stations
python manage.py runserver
```

Open http://127.0.0.1:8000/ for the map.

## API

```
GET /api/route/?start=Chicago,%20IL&finish=Dallas,%20TX
```

Swagger UI: http://127.0.0.1:8000/api/docs/ (OpenAPI file at `/api/schema/`,
which Postman can import). The response includes `map_url`, a link that opens
the route and fuel stops on a map.

The vehicle starts with a full tank. Station coordinates are the city of each
truck stop. The same stop keeps its lowest listed price. Routing uses one OSRM
call per distinct trip; repeats are cached.
