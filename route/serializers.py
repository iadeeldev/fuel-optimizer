from rest_framework import serializers


class PlaceSerializer(serializers.Serializer):
    label = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()


class FuelStopSerializer(serializers.Serializer):
    opis_id = serializers.IntegerField()
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    price_per_gallon = serializers.FloatField()
    mile_along_route = serializers.FloatField()
    distance_from_route_miles = serializers.FloatField()
    gallons = serializers.FloatField()
    cost_usd = serializers.FloatField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()


class RouteGeometrySerializer(serializers.Serializer):
    type = serializers.CharField()
    coordinates = serializers.ListField(child=serializers.ListField(child=serializers.FloatField()))


class RoutePlanSerializer(serializers.Serializer):
    start = PlaceSerializer()
    finish = PlaceSerializer()
    distance_miles = serializers.FloatField()
    duration_minutes = serializers.FloatField()
    total_fuel_cost_usd = serializers.FloatField()
    assumes_full_tank_at_start = serializers.BooleanField()
    mpg = serializers.IntegerField()
    max_range_miles = serializers.IntegerField()
    trip_fuel_gallons = serializers.FloatField()
    starting_tank_gallons = serializers.FloatField()
    purchased_fuel_gallons = serializers.FloatField()
    map_url = serializers.URLField(help_text="Open this link in a browser to see the route on a map with the fuel stops.")
    fuel_stops = FuelStopSerializer(many=True)
    route = RouteGeometrySerializer()
    notes = serializers.CharField()


class ErrorSerializer(serializers.Serializer):
    error = serializers.CharField()
