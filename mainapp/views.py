from django.shortcuts import get_object_or_404, redirect, render
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import SearchFilter

from mainapp.pagination import InternshipPagination, JobPagination, ResumePagination
from mainapp.throttling import InternshipThrottle, JobThrottle, ResumeThrottle
from .models import Job, Internship, resume
from .forms import JobForm, ResumeForm
from .serialiers import JobSerializer, ResumeSerializer, InternshipSerializer


def home_view(request):
    jobs = Job.objects.order_by('-created_at')[:6]
    internships = Internship.objects.order_by('-created_at')[:4]
    resumes = resume.objects.order_by('-created_at')[:4]

    context = {
        'jobs': jobs,
        'internships': internships,
        'resumes': resumes,
        'job_count': Job.objects.count(),
        'internship_count': Internship.objects.count(),
        'resume_count': resume.objects.count(),
    }
    return render(request, 'mainapp/index.html', context)


def job_detail(request, pk):
    job = get_object_or_404(Job, pk=pk)
    return render(request, 'mainapp/detail.html', {'item': job, 'type': 'job'})


def internship_detail(request, pk):
    item = get_object_or_404(Internship, pk=pk)
    return render(request, 'mainapp/detail.html', {'item': item, 'type': 'internship'})


def resume_detail(request, pk):
    item = get_object_or_404(resume, pk=pk)
    return render(request, 'mainapp/detail.html', {'item': item, 'type': 'resume'})


def create_listing(request, listing_type):
    form_config = {
        'job': (JobForm, 'Job', 'job_detail'),
        'resume': (ResumeForm, 'Resume', 'resume_detail'),
    }
    form_class, listing_title, detail_url = form_config.get(listing_type, (None, None, None))
    if form_class is None:
        return redirect('home')

    form = form_class(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        item = form.save()
        return redirect(detail_url, pk=item.pk)

    return render(request, 'mainapp/create.html', {
        'form': form,
        'listing_title': listing_title,
    })


class JobViewSet(viewsets.ModelViewSet):
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    pagination_class = JobPagination
    throttle_classes = [JobThrottle]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['company_name', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'status']
    filterset_fields = ['company_name', 'salary', 'required_experience', 'work_time', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'status']


class ResumeViewSet(viewsets.ModelViewSet):
    queryset = resume.objects.all()
    serializer_class = ResumeSerializer
    pagination_class = ResumePagination
    throttle_classes = [ResumeThrottle]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['name', 'surname', 'email', 'phone_number', 'experience', 'wanted_salary', 'wanted_working_condition', 'wanted_work_schedule_and_working_hours']
    filterset_fields = ['name', 'surname', 'email', 'phone_number', 'phone_number2', 'experience', 'wanted_salary', 'wanted_work_time', 'wanted_working_condition', 'wanted_work_schedule_and_working_hours']


class InternshipViewSet(viewsets.ModelViewSet):
    queryset = Internship.objects.all()
    serializer_class = InternshipSerializer
    pagination_class = InternshipPagination
    throttle_classes = [InternshipThrottle]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['company_name', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'status']
    filterset_fields = ['company_name', 'work_time', 'work_duration', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field']

