"""Idempotent loader of the full country/city reference data.

* Countries: ISO 3166-1 codes from ``mainapp/data/cities.json.gz``, names in en/ru/uz from Babel (CLDR).
* Cities: rows of the same file (GeoNames, see ``mainapp/data/build_geo_data.py``).

Works with real models and with historical models inside a migration (it never calls model methods).
Rows that already exist are matched, not recreated, so foreign keys of listings stay valid:
  - country: by ISO code, otherwise by the old (Russian/English) name;
  - city: by ``geoname_id``, otherwise by the old name inside the same country (legacy rows have no geoname_id).
Running it twice changes nothing (only differing rows are updated, nothing is inserted twice).
"""
import gzip
import json
from pathlib import Path

from babel import Locale

from .geo_utils import FEATURED_COUNTRY_CODES, build_search_text

DATA_FILE = Path(__file__).resolve().parent / 'data' / 'cities.json.gz'
BATCH_SIZE = 500

COUNTRY_FIELDS = ('name', 'code', 'name_en', 'name_ru', 'name_uz', 'priority')
CITY_FIELDS = ('name', 'name_en', 'name_ru', 'name_uz', 'population', 'geoname_id', 'search_text')


def load_geo_data(path=DATA_FILE):
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        return json.load(handle)


def _country_names(code, territories):
    return {lang: territories[lang].get(code, '') for lang in ('en', 'ru', 'uz')}


def _apply(instance, values, fields):
    """Set values on the instance; True when something changed."""
    changed = False
    for field in fields:
        if getattr(instance, field) != values[field]:
            setattr(instance, field, values[field])
            changed = True
    return changed


def seed_countries(country_model, data):
    """Create/update all countries. Returns ({code: country}, created, updated)."""
    territories = {lang: Locale(lang).territories for lang in ('en', 'ru', 'uz')}
    existing = list(country_model.objects.all())
    by_code = {c.code: c for c in existing if c.code}
    by_name = {c.name: c for c in existing}
    names_in_use = set(by_name)
    result, to_create, to_update = {}, [], []

    for code in data['countries']:
        names = _country_names(code, territories)
        english = names['en'] or code
        country = by_code.get(code) or by_name.get(names['ru']) or by_name.get(english)
        if country is not None and country.code and country.code != code:
            country = None  # a different country that happens to share the name
        priority = (100 - FEATURED_COUNTRY_CODES.index(code)) if code in FEATURED_COUNTRY_CODES else 0
        values = {
            'name': english, 'code': code,
            'name_en': english, 'name_ru': names['ru'] or english, 'name_uz': names['uz'] or english,
            'priority': priority,
        }
        if country is None:
            country = country_model(**values)
            to_create.append(country)
            names_in_use.add(english)
        else:
            if values['name'] != country.name and values['name'] in names_in_use:
                values['name'] = country.name  # keep the old name rather than break the unique constraint
            if values['name'] != country.name:
                names_in_use.discard(country.name)
                names_in_use.add(values['name'])
            if _apply(country, values, COUNTRY_FIELDS):
                to_update.append(country)
        result[code] = country

    country_model.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
    if to_update:
        country_model.objects.bulk_update(to_update, COUNTRY_FIELDS, batch_size=BATCH_SIZE)
    # bulk_create sets pks on PostgreSQL/SQLite(3.35+) but be explicit: reload what we created
    if to_create:
        fresh = {c.code: c for c in country_model.objects.filter(code__in=[c.code for c in to_create])}
        result.update(fresh)
    return result, len(to_create), len(to_update)


def seed_cities(country_model, city_model, data, countries):
    """Create/update cities of every country. Returns (created, updated)."""
    created = updated = 0
    for code, rows in data['cities'].items():
        country = countries.get(code)
        if country is None or not rows:
            continue
        existing = list(city_model.objects.filter(country_id=country.pk))
        by_geoname = {c.geoname_id: c for c in existing if c.geoname_id}
        legacy = {}
        for city in existing:
            if not city.geoname_id:
                legacy.setdefault(city.name, city)
        names_in_use = {c.name for c in existing}
        to_create, to_update, claimed = [], [], set()

        for geoname_id, name_en, name_ru, name_uz, population in rows:
            name_ru, name_uz = name_ru or name_en, name_uz or name_en
            values = {
                'name': name_en, 'name_en': name_en, 'name_ru': name_ru, 'name_uz': name_uz,
                'population': population, 'geoname_id': geoname_id,
                'search_text': build_search_text(name_en, name_ru, name_uz),
            }
            city = by_geoname.get(geoname_id)
            if city is None:
                for candidate in (name_ru, name_en):
                    match = legacy.get(candidate)
                    if match is not None and match.pk not in claimed:
                        city = match
                        break
            if city is None:
                if name_en in names_in_use:
                    continue  # same name already taken by another row of this country: keep it unique
                to_create.append(city_model(country_id=country.pk, **values))
                names_in_use.add(name_en)
                continue
            claimed.add(city.pk)
            if values['name'] != city.name:
                if values['name'] in names_in_use:
                    values['name'] = city.name
                else:
                    names_in_use.discard(city.name)
                    names_in_use.add(values['name'])
            if _apply(city, values, CITY_FIELDS):
                to_update.append(city)

        city_model.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
        if to_update:
            city_model.objects.bulk_update(to_update, CITY_FIELDS, batch_size=BATCH_SIZE)
        created += len(to_create)
        updated += len(to_update)
    return created, updated


def seed_geo_data(country_model, city_model, data=None):
    """Load everything. Returns (countries created, countries updated, cities created, cities updated)."""
    data = data or load_geo_data()
    countries, new_countries, changed_countries = seed_countries(country_model, data)
    new_cities, changed_cities = seed_cities(country_model, city_model, data, countries)
    return new_countries, changed_countries, new_cities, changed_cities
