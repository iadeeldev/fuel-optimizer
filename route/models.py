from django.db import models


class FuelStation(models.Model):
    """A truck stop from the fuel-price file, located at its city center."""

    opis_id = models.PositiveIntegerField()
    name = models.CharField(max_length=80)
    address = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=2)
    price = models.DecimalField(max_digits=6, decimal_places=3)
    latitude = models.FloatField()
    longitude = models.FloatField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["opis_id", "state", "city"],
                name="uniq_station_place",
            )
        ]
        indexes = [
            models.Index(fields=["state", "city"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state}) ${self.price}"
