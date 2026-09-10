from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.utils.translation import gettext_lazy as _

from .models import AccountProfile, Internship, Job, resume


class AdminUserForm(forms.ModelForm):
    display_name = forms.CharField(max_length=200, required=False, label='Имя')
    role = forms.ChoiceField(choices=AccountProfile._meta.get_field('role').choices, label='Роль')
    new_password = forms.CharField(
        required=False,
        min_length=8,
        widget=forms.PasswordInput,
        label='Новый пароль',
        help_text='Оставьте пустым, чтобы пароль не менять.',
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'is_active')
        labels = {
            'username': 'Логин',
            'email': 'Email',
            'first_name': 'Имя',
            'last_name': 'Фамилия',
            'is_active': 'Аккаунт активен',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.username == 'RoRed0':
            self.fields['username'].disabled = True
        profile = getattr(self.instance, 'account_profile', None)
        if profile:
            self.fields['display_name'].initial = profile.display_name
            self.fields['role'].initial = profile.role

    def save(self, commit=True):
        user = super().save(commit=commit)
        if self.cleaned_data.get('new_password'):
            user.set_password(self.cleaned_data['new_password'])
            user.save(update_fields=['password'])
        AccountProfile.objects.update_or_create(
            user=user,
            defaults={
                'role': self.cleaned_data['role'],
                'display_name': self.cleaned_data.get('display_name', ''),
            },
        )
        return user


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

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password, user=User(username=self.cleaned_data.get('username', '')))
        return password

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


class RoleForm(forms.Form):
    role = forms.ChoiceField(
        choices=(('company', _('Company')), ('worker', _('Worker'))),
        label=_('Account type'),
    )


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
            'status',
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
            'status': _('Status'),
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
            'status',
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
            'status': _('Status'),
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
            'status',
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
            'status': _('Status'),
        }
