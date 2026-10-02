import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class RouteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "route"

    def ready(self):
        # Load the 29,880 city list now so the first request does not pay for it.
        # Stations come from the database, which Django advises not to query here,
        # so they still load on the first request.
        from .services.geo import city_index

        try:
            city_index()
        except FileNotFoundError:
            logger.warning("City list not found; it will load on the first request.")
