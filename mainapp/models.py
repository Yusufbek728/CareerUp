from django.core.validators import RegexValidator
from django.contrib.auth.models import User
from django.db import models

phone_number_validator = RegexValidator(
    regex=r'^\+?(?=(?:\D*\d){8,15}\D*$)[0-9][0-9\s().-]*[0-9]$',
    message='Введите корректный номер телефона: 8–15 цифр, можно использовать +, пробелы, дефисы и скобки.',
)
STATUS_CHOICES = (
    ('qidirilyapti', 'Qidirilyapti'),
    ('topilgan', 'Topilgan'),
)
WORKING_CONDITIONS = (
    ('full_time', 'toliq vaqt'),
    ('part_time', 'yarim vaqt'),
    ('remote', 'masofaviy'),
)
WORK_FIELDS = (
    ('permament', 'har doimiy'),
    ('temporary', 'vaqtinchalik'),
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
    ('company', 'Company'),
    ('worker', 'Worker'),
)


class AccountProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='account_profile')
    role = models.CharField(max_length=20, choices=ACCOUNT_ROLES)
    display_name = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.display_name or self.user.username


class Job(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='jobs', null=True, blank=True)
    company_name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20, default='', validators=[phone_number_validator])
    phone_number2 = models.CharField(max_length=20, blank=True, null=True, default='', validators=[phone_number_validator])
    salary = models.IntegerField()
    required_experience = models.IntegerField()
    work_time = models.TimeField()
    job_title = models.CharField(max_length=200)
    requirements_of_job = models.TextField()
    working_condition = models.CharField(max_length=20, choices=WORKING_CONDITIONS, default='full_time')
    work_schedule_and_working_hours = models.CharField(max_length=20, choices=WORKING_DAYS, default='6/1')
    work_field = models.CharField(max_length=20, choices=WORK_FIELDS, default='full_time')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='qidirilyapti')
    def __str__(self):
        return self.job_title

class Internship(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='internships', null=True, blank=True)
    company_name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20, default='', validators=[phone_number_validator])
    phone_number2 = models.CharField(max_length=20, blank=True, null=True, default='', validators=[phone_number_validator])
    work_time = models.TimeField()
    work_duration = models.IntegerField()
    job_title = models.CharField(max_length=200)
    working_condition = models.CharField(max_length=20, choices=WORKING_CONDITIONS, default='full_time')
    work_schedule_and_working_hours = models.CharField(max_length=20, choices=WORKING_DAYS, default='6/1')
    work_field = models.CharField(max_length=20, choices=WORK_FIELDS, default='full_time')
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.job_title
    
class resume(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='resumes', null=True, blank=True)
    name = models.CharField(max_length=200)
    surname = models.CharField(max_length=200)
    email = models.EmailField()
    phone_number = models.CharField(max_length=20, default='', validators=[phone_number_validator])
    phone_number2 = models.CharField(max_length=20, blank=True, null=True, default='', validators=[phone_number_validator])
    experience = models.IntegerField()
    wanted_salary = models.IntegerField()
    wanted_work_time = models.TimeField()
    wanted_working_condition = models.CharField(max_length=20, choices=WORKING_CONDITIONS, default='full_time')
    wanted_work_schedule_and_working_hours = models.CharField(max_length=20, choices=WORKING_DAYS, default='6/1')
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='qidirilyapti')