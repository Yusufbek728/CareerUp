from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mainapp', '0021_seed_all_countries_cities'),
    ]

    operations = [
        migrations.AlterField(
            model_name='country',
            name='code',
            field=models.CharField(blank=True, help_text='ISO 3166-1 alpha-2', max_length=2, null=True, unique=True),
        ),
    ]
