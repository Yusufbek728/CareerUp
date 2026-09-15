from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mainapp', '0012_job_hourly_income'),
    ]

    operations = [
        migrations.AddField(
            model_name='accountprofile',
            name='company_photo',
            field=models.ImageField(blank=True, null=True, upload_to='company_photos/'),
        ),
        migrations.RenameField(
            model_name='job',
            old_name='company_logo',
            new_name='work_photo',
        ),
        migrations.RenameField(
            model_name='internship',
            old_name='company_logo',
            new_name='work_photo',
        ),
        migrations.AlterField(
            model_name='job',
            name='work_photo',
            field=models.ImageField(blank=True, null=True, upload_to='work_photos/'),
        ),
        migrations.AlterField(
            model_name='internship',
            name='work_photo',
            field=models.ImageField(blank=True, null=True, upload_to='work_photos/'),
        ),
    ]