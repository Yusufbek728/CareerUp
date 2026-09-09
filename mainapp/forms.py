from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from .models import Internship, Job, resume


class RegistrationForm(forms.Form):
    username = forms.CharField(max_length=150, label=_('Username'))
    email = forms.EmailField(label=_('Email'))
    password = forms.CharField(min_length=8, widget=forms.PasswordInput, label=_('Password'))
    password_confirm = forms.CharField(widget=forms.PasswordInput, label=_('Confirm password'))
    role = forms.ChoiceField(choices=(('company', _('Company')), ('worker', _('Worker'))), label=_('Account type'))
    display_name = forms.CharField(max_length=200, label=_('Display name'))

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(_('This username is already taken.'))
        return username

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('password') != cleaned_data.get('password_confirm'):
            raise forms.ValidationError(_('Passwords do not match.'))
        return cleaned_data


class LoginForm(forms.Form):
    username = forms.CharField(label=_('Username'))
    password = forms.CharField(widget=forms.PasswordInput, label=_('Password'))

    def clean(self):
        cleaned_data = super().clean()
        user = authenticate(username=cleaned_data.get('username'), password=cleaned_data.get('password'))
        if user is None:
            raise forms.ValidationError(_('Invalid username or password.'))
        cleaned_data['user'] = user
        return cleaned_data


class JobForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = (
            'company_name',
            'phone_number',
            'phone_number2',
            'salary',
            'required_experience',
            'work_time',
            'job_title',
            'requirements_of_job',
            'working_condition',
            'work_schedule_and_working_hours',
            'work_field',
        )
        widgets = {
            'work_time': forms.TimeInput(attrs={'type': 'time'}),
            'requirements_of_job': forms.Textarea(attrs={'rows': 4}),
        }
        labels = {
            'company_name': _('Company name'),
            'phone_number': _('Phone number'),
            'phone_number2': _('Additional phone number'),
            'salary': _('Salary'),
            'required_experience': _('Required experience'),
            'work_time': _('Work time'),
            'job_title': _('Job title'),
            'requirements_of_job': _('Requirements of job'),
            'working_condition': _('Working condition'),
            'work_schedule_and_working_hours': _('Work schedule and working hours'),
            'work_field': _('Work field'),
        }


class InternshipForm(forms.ModelForm):
    class Meta:
        model = Internship
        fields = (
            'company_name',
            'phone_number',
            'phone_number2',
            'work_time',
            'work_duration',
            'job_title',
            'working_condition',
            'work_schedule_and_working_hours',
            'work_field',
        )
        widgets = {
            'work_time': forms.TimeInput(attrs={'type': 'time'}),
        }
        labels = {
            'company_name': _('Company name'),
            'phone_number': _('Phone number'),
            'phone_number2': _('Additional phone number'),
            'work_time': _('Work time'),
            'work_duration': _('Work duration'),
            'job_title': _('Job title'),
            'working_condition': _('Working condition'),
            'work_schedule_and_working_hours': _('Work schedule and working hours'),
            'work_field': _('Work field'),
        }


class ResumeForm(forms.ModelForm):
    class Meta:
        model = resume
        fields = (
            'name',
            'surname',
            'email',
            'phone_number',
            'phone_number2',
            'experience',
            'wanted_salary',
            'wanted_work_time',
            'wanted_working_condition',
            'wanted_work_schedule_and_working_hours',
        )
        widgets = {
            'wanted_work_time': forms.TimeInput(attrs={'type': 'time'}),
        }
        labels = {
            'name': _('First name'),
            'surname': _('Last name'),
            'email': _('Email'),
            'phone_number': _('Phone number'),
            'phone_number2': _('Additional phone number'),
            'experience': _('Experience'),
            'wanted_salary': _('Wanted salary'),
            'wanted_work_time': _('Preferred work time'),
            'wanted_working_condition': _('Preferred working condition'),
            'wanted_work_schedule_and_working_hours': _('Preferred work schedule and working hours'),
        }
