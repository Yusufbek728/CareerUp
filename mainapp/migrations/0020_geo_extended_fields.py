from django.db import migrations, models


class Migration(migrations.Migration):
    """Schema for the full country/city reference: localized names, population, GeoNames id, search text.

    ``Country.code`` becomes nullable here and unique in 0022 (after 0021 turned the blank codes into NULL).
    """

    dependencies = [
        ('mainapp', '0019_seed_countries_cities'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='city',
            options={'ordering': ['-population', 'name'], 'verbose_name': 'city', 'verbose_name_plural': 'cities'},
        ),
        migrations.AlterModelOptions(
            name='country',
            options={'ordering': ['-priority', 'name'], 'verbose_name': 'country', 'verbose_name_plural': 'countries'},
        ),
        migrations.AddField(
            model_name='country',
            name='name_en',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='country',
            name='name_ru',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='country',
            name='name_uz',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='country',
            name='priority',
            field=models.SmallIntegerField(default=0, help_text='Higher values are listed first.'),
        ),
        migrations.AlterField(
            model_name='country',
            name='code',
            field=models.CharField(blank=True, help_text='ISO 3166-1 alpha-2', max_length=2, null=True),
        ),
        migrations.AlterField(
            model_name='city',
            name='name',
            field=models.CharField(max_length=150),
        ),
        migrations.AddField(
            model_name='city',
            name='name_en',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.AddField(
            model_name='city',
            name='name_ru',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.AddField(
            model_name='city',
            name='name_uz',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.AddField(
            model_name='city',
            name='population',
            field=models.PositiveBigIntegerField(db_index=True, default=0),
        ),
        migrations.AddField(
            model_name='city',
            name='geoname_id',
            field=models.PositiveIntegerField(blank=True, editable=False, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='city',
            name='search_text',
            field=models.TextField(blank=True, default='', editable=False),
        ),
    ]
