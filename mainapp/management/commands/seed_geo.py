from django.core.management.base import BaseCommand

from mainapp.geo_seed import seed_geo_data
from mainapp.models import City, Country


class Command(BaseCommand):
    help = (
        'Load (idempotently) all countries (ISO 3166-1) and the cities from mainapp/data/cities.json.gz. '
        'Existing rows are matched and updated in place, never duplicated. Safe to run repeatedly.'
    )

    def handle(self, *args, **options):
        new_countries, changed_countries, new_cities, changed_cities = seed_geo_data(Country, City)
        self.stdout.write(self.style.SUCCESS(
            f'Countries: {new_countries} added, {changed_countries} updated. '
            f'Cities: {new_cities} added, {changed_cities} updated.'
        ))
