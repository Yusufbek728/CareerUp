from warnings import filters

from django.shortcuts import render
from rest_framework import viewsets
from mainapp.pagination import InternshipPagination, JobPagination, ResumePagination
from mainapp.throttling import InternshipThrottle, JobThrottle, ResumeThrottle
from .serialiers import JobSerializer, ResumeSerializer, InternshipSerializer
from .models import Job, resume, Internship 
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter

class JobViewSet(viewsets.ModelViewSet):
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    pagination_class = JobPagination
    throttle_classes = [JobThrottle]
    filter_backends = [SearchFilter]
    search_fields = ['company_name', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'status']
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["company_name", "salary", "required_experience", "work_time", "job_title", "working_condition", "work_schedule_and_working_hours", "work_field", "status"]
class ResumeViewSet(viewsets.ModelViewSet):
    queryset = resume.objects.all()
    serializer_class = ResumeSerializer
    pagination_class = ResumePagination
    throttle_classes = [ResumeThrottle]
    filter_backends = [SearchFilter]
    search_fields = ['name', 'surname', 'email', 'phone_number', 'experience', 'wanted_salary', 'wanted_working_condition', 'wanted_work_schedule_and_working_hours']
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["name", "surname", "email", "phone_number", "phone_number2", "experience", "wanted_salary", "wanted_work_time", "wanted_working_condition", "wanted_work_schedule_and_working_hours"]

class InternshipViewSet(viewsets.ModelViewSet):
    queryset = Internship.objects.all()
    serializer_class = InternshipSerializer
    pagination_class = InternshipPagination
    throttle_classes = [InternshipThrottle]
    filter_backends = [SearchFilter]
    search_fields = ['company_name', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'status']
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["company_name", "work_time", "work_duration", "job_title", "working_condition", "work_schedule_and_working_hours", "work_field"]

