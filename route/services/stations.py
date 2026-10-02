"""In-memory station list and its location index, so a request does not re-read the database."""

from ..models import FuelStation
from .routing import StationIndex

_stations = None
_index = None


def all_stations():
    global _stations
    if _stations is None:
        _stations = list(FuelStation.objects.all())
    return _stations


def station_index():
    global _index
    if _index is None:
        _index = StationIndex(all_stations())
    return _index


def clear_station_cache():
    global _stations, _index
    _stations = None
    _index = None
