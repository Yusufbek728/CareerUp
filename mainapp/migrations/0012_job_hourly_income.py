from decimal import Decimal

from django.db import migrations, models


def calculate_hourly_income(apps, schema_editor):
    Job = apps.get_model('mainapp', 'Job')
    for job in Job.objects.all():
        job.hourly_income = Decimal(job.salary) / Decimal(job.work_time) if job.work_time else 0
        job.save(update_fields=['hourly_income'])


class Migration(migrations.Migration):

    dependencies = [
        ('mainapp', '0011_alter_accountprofile_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='hourly_income',
            field=models.DecimalField(decimal_places=2, default=0, editable=False, max_digits=12),
        ),
        migrations.RunPython(calculate_hourly_income, migrations.RunPython.noop),
    ]