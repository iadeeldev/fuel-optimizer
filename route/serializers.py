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


class PlanOptionSerializer(serializers.Serializer):
    fuel_stops = FuelStopSerializer(many=True)
    stop_count = serializers.IntegerField()
    total_fuel_cost_usd = serializers.FloatField(help_text="Money spent at the fuel stops.")
    trip_fuel_cost_usd = serializers.FloatField(
        allow_null=True,
        help_text="Cost of all fuel the trip burns, including the starting tank.",
    )
    purchased_fuel_gallons = serializers.FloatField()
    stop_penalty_usd = serializers.FloatField(help_text="Dollars charged per stop while planning. 0 for cheapest.")


class PlansSerializer(serializers.Serializer):
    cheapest = PlanOptionSerializer(help_text="Lowest fuel bill.")
    fewer_stops = PlanOptionSerializer(help_text="Slightly higher bill, far fewer stops.")


class RouteGeometrySerializer(serializers.Serializer):
    type = serializers.CharField()
    coordinates = serializers.ListField(child=serializers.ListField(child=serializers.FloatField()))


class RoutePlanSerializer(serializers.Serializer):
    start = PlaceSerializer()
    finish = PlaceSerializer()
    distance_miles = serializers.FloatField()
    duration_minutes = serializers.FloatField()
    total_fuel_cost_usd = serializers.FloatField(help_text="Money spent at the fuel stops of the chosen plan.")
    trip_fuel_cost_usd = serializers.FloatField(
        allow_null=True,
        help_text="Cost of all fuel the trip burns, including the starting tank, for the chosen plan.",
    )
    assumes_full_tank_at_start = serializers.BooleanField()
    mpg = serializers.IntegerField()
    max_range_miles = serializers.IntegerField()
    trip_fuel_gallons = serializers.FloatField()
    starting_tank_gallons = serializers.FloatField()
    starting_tank_price_per_gallon = serializers.FloatField(
        allow_null=True,
        help_text="Price used to value the starting tank: the average along the route.",
    )
    purchased_fuel_gallons = serializers.FloatField()
    map_url = serializers.URLField(help_text="Open this link in a browser to see the route on a map with the fuel stops.")
    plan = serializers.ChoiceField(
        choices=["cheapest", "fewer_stops"],
        help_text="The plan whose stops and cost fill fuel_stops and total_fuel_cost_usd.",
    )
    fuel_stops = FuelStopSerializer(many=True)
    plans = PlansSerializer()
    plan_comparison = serializers.CharField()
    route = RouteGeometrySerializer()
    notes = serializers.CharField()


class ErrorSerializer(serializers.Serializer):
    error = serializers.CharField()


class ThrottledSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="For example: Request was throttled. Expected available in 42 seconds.")
