from django import forms

from .models import Job, resume


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
