from decimal import Decimal

from django.core.validators import RegexValidator
from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _

phone_number_validator = RegexValidator(
    regex=r'^\+?(?=(?:\D*\d){8,15}\D*$)[0-9][0-9\s().-]*[0-9]$',
    message='Введите корректный номер телефона: 8–15 цифр, можно использовать +, пробелы, дефисы и скобки.',
)
STATUS_CHOICES = (
    ('qidirilyapti', _('Still looking')),
    ('topilgan', _('Not looking')),
)
WORKING_CONDITIONS = (
    ('full_time', _('Full time')),
    ('part_time', _('Part time')),
    ('remote', _('Remote')),
)
WORK_FIELDS = (
    ('permament', _('Permanent')),
    ('temporary', _('Temporary')),
)
WORKING_DAYS = (
    ('6/1', '6/1'),
    ('5/2', '5/2'),
    ('4/3', '4/3'),
    ('3/4', '3/4'),
    ('2/5', '2/5'),
    ('1/6', '1/6'),
)

ACCOUNT_ROLES = (
    ('company', _('Company')),
    ('worker', _('Worker')),
    ('creator', _('Creator')),
)


class AccountProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='account_profile')
    role = models.CharField(max_length=20, choices=ACCOUNT_ROLES)
    display_name = models.CharField(max_length=200, blank=True)
    company_photo = models.ImageField(upload_to='company_photos/', blank=True, null=True)

    def __str__(self):
        return self.display_name or self.user.username


class Job(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='jobs', null=True, blank=True)
    company_name = models.CharField(max_length=200)
    work_photo = models.ImageField(upload_to='work_photos/', blank=True, null=True)
    phone_number = models.CharField(max_length=20, default='', validators=[phone_number_validator])
    phone_number2 = models.CharField(max_length=20, blank=True, null=True, default='', validators=[phone_number_validator])
    salary = models.IntegerField()
    hourly_income = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    required_experience = models.IntegerField()
    work_time = models.IntegerField()
    job_title = models.CharField(max_length=200)
    requirements_of_job = models.TextField()
    working_condition = models.CharField(max_length=20, choices=WORKING_CONDITIONS, default='full_time')
    work_schedule_and_working_hours = models.CharField(max_length=20, choices=WORKING_DAYS, default='6/1')
    work_field = models.CharField(max_length=20, choices=WORK_FIELDS, default='full_time')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='qidirilyapti')

    def save(self, *args, **kwargs):
        self.hourly_income = Decimal(self.salary) / Decimal(self.work_time) if self.work_time else 0
        super().save(*args, **kwargs)

    def __str__(self):
        return self.job_title

class Internship(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='internships', null=True, blank=True)
    company_name = models.CharField(max_length=200)
    work_photo = models.ImageField(upload_to='work_photos/', blank=True, null=True)
    phone_number = models.CharField(max_length=20, default='', validators=[phone_number_validator])
    phone_number2 = models.CharField(max_length=20, blank=True, null=True, default='', validators=[phone_number_validator])
    work_time = models.IntegerField()
    work_duration = models.IntegerField()
    job_title = models.CharField(max_length=200)
    working_condition = models.CharField(max_length=20, choices=WORKING_CONDITIONS, default='full_time')
    work_schedule_and_working_hours = models.CharField(max_length=20, choices=WORKING_DAYS, default='6/1')
    work_field = models.CharField(max_length=20, choices=WORK_FIELDS, default='full_time')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='qidirilyapti')
    def __str__(self):
        return self.job_title
    
class Resume(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='resumes', null=True, blank=True)
    name = models.CharField(max_length=200)
    surname = models.CharField(max_length=200)
    photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)
    email = models.EmailField()
    phone_number = models.CharField(max_length=20, default='', validators=[phone_number_validator])
    phone_number2 = models.CharField(max_length=20, blank=True, null=True, default='', validators=[phone_number_validator])
    experience = models.IntegerField()
    wanted_salary = models.IntegerField()
    wanted_work_time = models.IntegerField()
    wanted_working_condition = models.CharField(max_length=20, choices=WORKING_CONDITIONS, default='full_time')
    wanted_work_schedule_and_working_hours = models.CharField(max_length=20, choices=WORKING_DAYS, default='6/1')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='qidirilyapti')