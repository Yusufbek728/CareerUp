from django.db import migrations

from mainapp.geo_data import seed_geo


def forwards(apps, schema_editor):
    seed_geo(apps.get_model('mainapp', 'Country'), apps.get_model('mainapp', 'City'))


class Migration(migrations.Migration):

    dependencies = [
        ('mainapp', '0018_country_city_location'),
    ]

    operations = [
        # Обратная операция — noop: справочник может использоваться объявлениями, откат его не удаляет.
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
