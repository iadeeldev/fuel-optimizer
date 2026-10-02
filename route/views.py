from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .serializers import ErrorSerializer, RoutePlanSerializer
from .services.planner import PlanError, build_plan


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
    ],
    responses={
        200: RoutePlanSerializer,
        400: ErrorSerializer,
        502: ErrorSerializer,
    },
)
@api_view(["GET"])
def route_plan(request):
    start = request.query_params.get("start", "")
    finish = request.query_params.get("finish", "")
    if not start.strip() or not finish.strip():
        return Response(
            {"error": "Pass start and finish as US cities, for example Chicago, IL."},
            status=400,
        )
    try:
        plan = build_plan(start, finish)
        map_url = request.build_absolute_uri(reverse("map")) + "?" + urlencode(
            {"start": start.strip(), "finish": finish.strip()}
        )
        return Response({**plan, "map_url": map_url})
    except PlanError as exc:
        return Response({"error": str(exc)}, status=exc.status)


@require_GET
def map_page(request):
    return render(
        request,
        "route/map.html",
        {
            "start": request.GET.get("start", "Chicago, IL"),
            "finish": request.GET.get("finish", "Dallas, TX"),
        },
    )
