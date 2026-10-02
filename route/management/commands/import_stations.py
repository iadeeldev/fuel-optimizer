from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from route.models import FuelStation
from route.services.prices import load_stations
from route.services.stations import clear_station_cache


class Command(BaseCommand):
    help = "Load truck stops from the fuel-price PDF and attach city coordinates."

    def add_arguments(self, parser):
        parser.add_argument("--pdf", default="")

    def handle(self, *args, **options):
        pdf_path = Path(options["pdf"] or settings.BASE_DIR / "data" / "fuel-prices.pdf")
        cities = settings.BASE_DIR / "data" / "us_cities.csv"
        if not pdf_path.exists():
            self.stderr.write(f"PDF not found: {pdf_path}")
            return
        self.stdout.write(f"Reading {pdf_path.name} ...")
        rows, stats = load_stations(pdf_path, cities)
        FuelStation.objects.all().delete()
        FuelStation.objects.bulk_create(
            [FuelStation(**row) for row in rows],
            batch_size=1000,
        )
        clear_station_cache()
        self.stdout.write(
            "Imported {stations} stations from {rows} price rows "
            "({skipped_non_us} outside the US, {unmatched_city} cities unmatched, "
            "{bad_price} bad prices).".format(**stats)
        )
