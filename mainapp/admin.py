from django.contrib import admin
from .models import Job, Internship, resume

@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'job_title', 'salary', 'required_experience', 'work_time', 'status', 'created_at', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'requirements_of_job',)
    list_filter = ('status', 'created_at')
    search_fields = ('company_name', 'job_title')
 
@admin.register(Internship)
class InternshipAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'job_title', 'work_time', 'work_duration', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'created_at',)
    search_fields = ('company_name', 'job_title')
    list_filter = ('created_at',)

@admin.register(resume)
class ResumeAdmin(admin.ModelAdmin):
    list_display = ('name', 'surname', 'email', 'phone_number', 'experience', 'wanted_salary', 'wanted_work_time', 'wanted_working_condition', 'wanted_work_schedule_and_working_hours', 'created_at',)
    search_fields = ('name', 'surname', 'email')
    list_filter = ('created_at',)

