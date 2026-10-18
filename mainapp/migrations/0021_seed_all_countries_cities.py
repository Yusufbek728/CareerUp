from django.db import migrations

from mainapp.geo_seed import seed_geo_data


def forwards(apps, schema_editor):
    Country = apps.get_model('mainapp', 'Country')
    City = apps.get_model('mainapp', 'City')
    # Blank codes would violate the unique constraint added in 0022 (several '' values); NULLs do not.
    Country.objects.filter(code='').update(code=None)
    # Existing rows (countries/cities seeded by 0019 or created by hand) are matched and updated in place,
    # so listings that reference them keep working.
    seed_geo_data(Country, City)


class Migration(migrations.Migration):

    dependencies = [
        ('mainapp', '0020_geo_extended_fields'),
    ]

    operations = [
        # Reverse is a no-op: the reference data may already be used by listings.
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
