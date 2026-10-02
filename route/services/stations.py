"""In-memory station list so a request does not re-read the PDF."""

from ..models import FuelStation

_stations = None


def all_stations():
    global _stations
    if _stations is None:
        _stations = list(FuelStation.objects.all())
    return _stations


def clear_station_cache():
    global _stations
    _stations = None
