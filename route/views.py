from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import require_GET
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .serializers import ErrorSerializer, RoutePlanSerializer
from .services.planner import DEFAULT_PLAN, PLAN_NAMES, PlanError, build_plan


class RouteRateThrottle(AnonRateThrottle):
    """Per-client limit, set by ROUTE_RATE_LIMIT, so no one client can exhaust the free OSRM server."""

    scope = "route"


@extend_schema(
    summary="Plan a driving route and the cheapest fuel stops",
    description=(
        "Takes a start and finish inside the USA. Returns the driving route, "
        "where to refuel, and the total fuel cost. The vehicle starts with a "
        "full tank, has a 500 mile range, and gets 10 miles per gallon."
    ),
    parameters=[
        OpenApiParameter(
            name="start",
            type=str,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Start place. A US city, with or without a state. Example: Chicago, IL",
        ),
        OpenApiParameter(
            name="finish",
            type=str,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Finish place. A US city, with or without a state. Example: Dallas, TX",
        ),
        OpenApiParameter(
            name="plan",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=list(PLAN_NAMES),
            default=DEFAULT_PLAN,
            description=(
                "Which plan fills fuel_stops and total_fuel_cost_usd. cheapest is the "
                "lowest fuel bill; fewer_stops stops far less for a slightly higher bill. "
                "Both plans are always returned under plans."
            ),
        ),
    ],
    responses={
        200: RoutePlanSerializer,
        400: ErrorSerializer,
        429: None,
        502: ErrorSerializer,
    },
)
# Compressed here rather than site-wide: this reply holds no secrets, while
# pages with CSRF tokens (the admin) should not be gzipped (BREACH).
@gzip_page
@api_view(["GET"])
@throttle_classes([RouteRateThrottle])
def route_plan(request):
    start = request.query_params.get("start", "")
    finish = request.query_params.get("finish", "")
    if not start.strip() or not finish.strip():
        return Response(
            {"error": "Pass start and finish as US cities, for example Chicago, IL."},
            status=400,
        )
    choice = request.query_params.get("plan", DEFAULT_PLAN)
    if choice not in PLAN_NAMES:
        return Response(
            {"error": "plan must be cheapest or fewer_stops."},
            status=400,
        )
    try:
        plan = build_plan(start, finish, choice)
        map_url = request.build_absolute_uri(reverse("map")) + "?" + urlencode(
            {"start": start.strip(), "finish": finish.strip(), "plan": choice}
        )
        return Response({**plan, "map_url": map_url})
    except PlanError as exc:
        return Response({"error": str(exc)}, status=exc.status)


@require_GET
def map_page(request):
    choice = request.GET.get("plan", DEFAULT_PLAN)
    return render(
        request,
        "route/map.html",
        {
            "start": request.GET.get("start", "Chicago, IL"),
            "finish": request.GET.get("finish", "Dallas, TX"),
            "plan": choice if choice in PLAN_NAMES else DEFAULT_PLAN,
        },
    )
