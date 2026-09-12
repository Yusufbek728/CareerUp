from django.db.models import Q
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions, status, viewsets
from rest_framework.filters import SearchFilter
from rest_framework.response import Response

from mainapp.pagination import InternshipPagination, JobPagination, ResumePagination
from mainapp.throttling import InternshipThrottle, JobThrottle, ResumeThrottle
from .models import AccountProfile, Job, Internship, Resume
from .forms import (
    AccountSettingsForm,
    AdminUserForm,
    InternshipForm,
    JobForm,
    LoginForm,
    RegistrationForm,
    ResumeForm,
    RoleForm,
)
from .serialiers import JobSerializer, ResumeSerializer, InternshipSerializer, RegistrationSerializer


def is_super_admin(user):
    return user.is_active and user.is_superuser


def can_create_listing(user, listing_type):
    if user.is_superuser:
        return True

    role = getattr(getattr(user, 'account_profile', None), 'role', None)
    if role == 'creator':
        return True

    if listing_type in {'job', 'internship'}:
        return role == 'company'
    if listing_type == 'resume':
        return role == 'worker'
    return False


def super_admin_forbidden(request):
    return HttpResponseForbidden(
        f'Доступ запрещен для пользователя {request.user.username}.'
    )


def home_view(request):
    search_query = request.GET.get('q', '').strip()
    jobs = Job.objects.all()
    internships = Internship.objects.all()
    resumes = Resume.objects.all()

    if search_query:
        jobs = jobs.filter(
            Q(company_name__icontains=search_query)
            | Q(job_title__icontains=search_query)
            | Q(work_field__icontains=search_query)
            | Q(working_condition__icontains=search_query)
            | Q(work_schedule_and_working_hours__icontains=search_query)
            | Q(owner__username__icontains=search_query)
            | Q(owner__account_profile__display_name__icontains=search_query)
        )
        internships = internships.filter(
            Q(company_name__icontains=search_query)
            | Q(job_title__icontains=search_query)
            | Q(work_field__icontains=search_query)
            | Q(working_condition__icontains=search_query)
            | Q(work_schedule_and_working_hours__icontains=search_query)
            | Q(owner__username__icontains=search_query)
            | Q(owner__account_profile__display_name__icontains=search_query)
        )
        resumes = resumes.filter(
            Q(name__icontains=search_query)
            | Q(surname__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(wanted_working_condition__icontains=search_query)
            | Q(wanted_work_schedule_and_working_hours__icontains=search_query)
            | Q(owner__username__icontains=search_query)
            | Q(owner__account_profile__display_name__icontains=search_query)
        )

    jobs = jobs.order_by('-created_at')[:6]
    internships = internships.order_by('-created_at')[:4]
    resumes = resumes.order_by('-created_at')[:4]

    context = {
        'jobs': jobs,
        'internships': internships,
        'resumes': resumes,
        'job_count': Job.objects.count(),
        'internship_count': Internship.objects.count(),
        'resume_count': Resume.objects.count(),
        'search_query': search_query,
    }
    return render(request, 'mainapp/index.html', context)


def job_detail(request, pk):
    job = get_object_or_404(Job, pk=pk)
    return render(request, 'mainapp/detail.html', {'item': job, 'type': 'job'})


def internship_detail(request, pk):
    item = get_object_or_404(Internship, pk=pk)
    return render(request, 'mainapp/detail.html', {'item': item, 'type': 'internship'})


def resume_detail(request, pk):
    item = get_object_or_404(Resume, pk=pk)
    return render(request, 'mainapp/detail.html', {'item': item, 'type': 'resume'})


@login_required
def create_listing(request, listing_type):
    form_config = {
        'job': (JobForm, 'Job', 'job_detail'),
        'internship': (InternshipForm, 'Internship', 'internship_detail'),
        'resume': (ResumeForm, 'Resume', 'resume_detail'),
    }
    form_class, listing_title, detail_url = form_config.get(listing_type, (None, None, None))
    if form_class is None:
        return redirect('home')

    if not can_create_listing(request.user, listing_type):
        return redirect('home')

    form = form_class(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        item.owner = request.user
        item.save()
        return redirect(detail_url, pk=item.pk)

    return render(request, 'mainapp/create.html', {
        'form': form,
        'listing_title': listing_title,
    })


@login_required
def choose_role(request):
    profile = getattr(request.user, 'account_profile', None)
    if profile and profile.role:
        return redirect('home')

    form = RoleForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        AccountProfile.objects.update_or_create(
            user=request.user,
            defaults={
                'role': form.cleaned_data['role'],
                'display_name': request.user.get_full_name() or request.user.username,
            },
        )
        return redirect('home')

    return render(request, 'mainapp/choose_role.html', {'form': form})


def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        user = User.objects.create_user(username=data['username'], email=data['email'], password=data['password'])
        from .models import AccountProfile
        AccountProfile.objects.create(user=user, role=data['role'], display_name=data['display_name'])
        login(request, user)
        return redirect('home')
    return render(request, 'mainapp/auth.html', {'form': form, 'auth_title': 'Register'})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.cleaned_data['user'])
        next_url = request.GET.get('next', '')
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect('home')
    return render(request, 'mainapp/auth.html', {'form': form, 'auth_title': 'Login'})


def logout_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    logout(request)
    return redirect('home')


@login_required
def my_listings(request):
    context = {
        'jobs': Job.objects.filter(owner=request.user).order_by('-created_at'),
        'internships': Internship.objects.filter(owner=request.user).order_by('-created_at'),
        'resumes': Resume.objects.filter(owner=request.user).order_by('-created_at'),
    }
    return render(request, 'mainapp/my_listings.html', context)


@login_required
def account_settings(request):
    profile = getattr(request.user, 'account_profile', None)
    form = AccountSettingsForm(
        request.POST or None,
        user=request.user,
        profile=profile,
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        update_session_auth_hash(request, request.user)
        return redirect('account_settings')
    if request.method == 'POST':
        form.data = form.data.copy()
        form.data['current_password'] = ''
    return render(request, 'mainapp/account_settings.html', {'form': form})


@login_required
def edit_listing(request, listing_type, pk):
    config = {
        'job': (Job, JobForm, 'job_detail'),
        'internship': (Internship, InternshipForm, 'internship_detail'),
        'resume': (Resume, ResumeForm, 'resume_detail'),
    }
    model, form_class, detail_url = config.get(listing_type, (None, None, None))
    if model is None:
        return redirect('home')
    item = get_object_or_404(model, pk=pk, owner=request.user)
    form = form_class(request.POST or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect(detail_url, pk=item.pk)
    return render(request, 'mainapp/create.html', {'form': form, 'listing_title': 'Edit ' + listing_type.title()})


@login_required
def super_admin(request):
    if not is_super_admin(request.user):
        return super_admin_forbidden(request)

    user_form = None
    selected_user = None
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_user':
            selected_user = get_object_or_404(User, pk=request.POST.get('user_id'))
            user_form = AdminUserForm(request.POST, instance=selected_user)
            if user_form.is_valid():
                user_form.save()
                return redirect('super_admin')
        elif action == 'delete_user':
            selected_user = get_object_or_404(User, pk=request.POST.get('user_id'))
            if selected_user != request.user and not selected_user.is_superuser:
                selected_user.delete()
            return redirect('super_admin')
        elif action == 'delete_listing':
            listing_map = {'job': Job, 'internship': Internship, 'resume': Resume}
            model = listing_map.get(request.POST.get('listing_type'))
            if model:
                get_object_or_404(model, pk=request.POST.get('listing_id')).delete()
            return redirect('super_admin')

    search_query = request.GET.get('q', '').strip()
    if request.method == 'GET' and request.GET.get('edit_user'):
        selected_user = get_object_or_404(User, pk=request.GET['edit_user'])
        user_form = AdminUserForm(instance=selected_user)
    users = User.objects.select_related('account_profile').order_by('-date_joined')
    if search_query:
        users = users.filter(
            Q(username__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(first_name__icontains=search_query)
            | Q(last_name__icontains=search_query)
            | Q(account_profile__display_name__icontains=search_query)
        )

    return render(request, 'mainapp/super_admin.html', {
        'users': users,
        'jobs': Job.objects.select_related('owner').order_by('-created_at'),
        'internships': Internship.objects.select_related('owner').order_by('-created_at'),
        'resumes': Resume.objects.select_related('owner').order_by('-created_at'),
        'search_query': search_query,
        'user_form': user_form,
        'selected_user': selected_user,
    })


@login_required
def super_admin_edit_listing(request, listing_type, pk):
    if not is_super_admin(request.user):
        return super_admin_forbidden(request)

    config = {
        'job': (Job, JobForm, 'Вакансия'),
        'internship': (Internship, InternshipForm, 'Стажировка'),
        'resume': (Resume, ResumeForm, 'Резюме'),
    }
    model, form_class, title = config.get(listing_type, (None, None, None))
    if model is None:
        return redirect('super_admin')
    item = get_object_or_404(model, pk=pk)
    form = form_class(request.POST or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('super_admin')
    return render(request, 'mainapp/create.html', {
        'form': form,
        'listing_title': 'Изменить ' + title,
    })


class RegistrationAPIView(generics.CreateAPIView):
    serializer_class = RegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        user = User.objects.get(username=response.data['username'])
        from rest_framework_simplejwt.tokens import RefreshToken
        token = RefreshToken.for_user(user)
        response.data['refresh'] = str(token)
        response.data['access'] = str(token.access_token)
        return response


class OwnerModelViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def perform_create(self, serializer):
        if not self.request.user.is_authenticated:
            from rest_framework.exceptions import NotAuthenticated
            raise NotAuthenticated('Registration and login are required to create a listing.')
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        if not self.request.user.is_authenticated or serializer.instance.owner_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You can edit only your own listings.')
        serializer.save()

    def perform_destroy(self, instance):
        if not self.request.user.is_authenticated or instance.owner_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You can delete only your own listings.')
        instance.delete()


class JobViewSet(OwnerModelViewSet):
    queryset = Job.objects.all().order_by('-created_at', '-pk')
    serializer_class = JobSerializer
    pagination_class = JobPagination
    throttle_classes = [JobThrottle]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['company_name', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'status', 'owner__username', 'owner__account_profile__display_name']
    filterset_fields = ['company_name', 'salary', 'required_experience', 'work_time', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'status']


class ResumeViewSet(OwnerModelViewSet):
    queryset = Resume.objects.all().order_by('-created_at', '-pk')
    serializer_class = ResumeSerializer
    pagination_class = ResumePagination
    throttle_classes = [ResumeThrottle]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['name', 'surname', 'email', 'phone_number', 'experience', 'wanted_salary', 'wanted_working_condition', 'wanted_work_schedule_and_working_hours', 'owner__username', 'owner__account_profile__display_name']
    filterset_fields = ['name', 'surname', 'email', 'phone_number', 'phone_number2', 'experience', 'wanted_salary', 'wanted_work_time', 'wanted_working_condition', 'wanted_work_schedule_and_working_hours']


class InternshipViewSet(OwnerModelViewSet):
    queryset = Internship.objects.all().order_by('-created_at', '-pk')
    serializer_class = InternshipSerializer
    pagination_class = InternshipPagination
    throttle_classes = [InternshipThrottle]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['company_name', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'status', 'owner__username', 'owner__account_profile__display_name']
    filterset_fields = ['company_name', 'work_time', 'work_duration', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field']

