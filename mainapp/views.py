from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.core.paginator import Paginator
from django.conf import settings
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponseForbidden, HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import get_language, gettext, gettext_lazy as _
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions, status, viewsets
from rest_framework.filters import SearchFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from mainapp.pagination import InternshipPagination, JobPagination, ResumePagination
from mainapp.throttling import CityThrottle, InternshipThrottle, JobThrottle, ResumeThrottle
from mainapp import ratelimit
from .geo_utils import normalize_search
from .models import AccountProfile, City, Internship, Job, ListingInteraction, Resume
from .forms import (
    AccountSettingsForm,
    AdminUserForm,
    InternshipForm,
    JobForm,
    ListingFilterForm,
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
    if listing_type in {'job', 'internship'}:
        return role == 'company'
    if listing_type == 'resume':
        return role == 'worker'
    return False


def super_admin_forbidden(request):
    return HttpResponseForbidden(
        _('Access denied for user %(username)s.') % {'username': request.user.username}
    )


def filter_listings_by_query(queryset, query, fields):
    if not query:
        return queryset
    conditions = Q()
    for field in fields:
        conditions |= Q(**{field: query})
    return queryset.filter(conditions)


def filter_by_location(queryset, country, city):
    if country:
        queryset = queryset.filter(country=country)
    if city:
        queryset = queryset.filter(city=city)
    return queryset


def get_page_numbers(page_obj, max_pages=9):
    first_page = max(1, page_obj.number - max_pages // 2)
    last_page = min(page_obj.paginator.num_pages, first_page + max_pages - 1)
    first_page = max(1, last_page - max_pages + 1)
    return range(first_page, last_page + 1)


def annotate_listing_engagement(queryset, user):
    user_id = user.pk if user.is_authenticated else -1
    return queryset.annotate(
        like_count=Count(
            'interactions',
            filter=Q(interactions__liked_at__isnull=False),
            distinct=True,
        ),
        user_liked_count=Count(
            'interactions',
            filter=Q(interactions__user_id=user_id, interactions__liked_at__isnull=False),
            distinct=True,
        ),
        user_favorited_count=Count(
            'interactions',
            filter=Q(interactions__user_id=user_id, interactions__favorited_at__isnull=False),
            distinct=True,
        ),
    )


def build_homepage_context(request, listing_type=None):
    search_query = request.GET.get('q', '').strip()
    jobs = Job.objects.select_related('country', 'city')
    internships = Internship.objects.select_related('country', 'city')
    resumes = Resume.objects.select_related('country', 'city')
    filters = ListingFilterForm(request.GET) if listing_type in {'job', 'internship', 'resume'} else None
    salary_slider_max = 0

    if listing_type == 'job':
        internships = Internship.objects.none()
        resumes = Resume.objects.none()
        salary_slider_max = Job.objects.aggregate(max_salary=Max('salary'))['max_salary'] or 0
    elif listing_type == 'internship':
        jobs = Job.objects.none()
        resumes = Resume.objects.none()
    elif listing_type == 'resume':
        jobs = Job.objects.none()
        internships = Internship.objects.none()
        salary_slider_max = Resume.objects.aggregate(max_salary=Max('wanted_salary'))['max_salary'] or 0

    jobs = filter_listings_by_query(
        jobs,
        search_query,
        [
            'company_name__icontains',
            'job_title__icontains',
            'work_field__icontains',
            'working_condition__icontains',
            'work_schedule_and_working_hours__icontains',
            'owner__username__icontains',
            'owner__account_profile__display_name__icontains',
        ],
    )
    internships = filter_listings_by_query(
        internships,
        search_query,
        [
            'company_name__icontains',
            'job_title__icontains',
            'work_field__icontains',
            'working_condition__icontains',
            'work_schedule_and_working_hours__icontains',
            'owner__username__icontains',
            'owner__account_profile__display_name__icontains',
        ],
    )
    resumes = filter_listings_by_query(
        resumes,
        search_query,
        [
            'name__icontains',
            'surname__icontains',
            'email__icontains',
            'wanted_working_condition__icontains',
            'wanted_work_schedule_and_working_hours__icontains',
            'owner__username__icontains',
            'owner__account_profile__display_name__icontains',
        ],
    )

    if filters is not None and filters.is_valid():
        filter_fields = (
            ('status', 'status'),
            ('working_condition', 'working_condition'),
            ('work_field', 'work_field'),
            ('work_schedule_and_working_hours', 'work_schedule_and_working_hours'),
        )
        country = filters.cleaned_data.get('country')
        city = filters.cleaned_data.get('city')
        if listing_type == 'job':
            jobs = filter_by_location(jobs, country, city)
            for form_field, model_field in filter_fields:
                value = filters.cleaned_data[form_field]
                if value:
                    jobs = jobs.filter(**{model_field: value})
            if filters.cleaned_data['salary_min'] is not None:
                jobs = jobs.filter(salary__gte=filters.cleaned_data['salary_min'])
            if filters.cleaned_data['salary_max'] is not None:
                jobs = jobs.filter(salary__lte=filters.cleaned_data['salary_max'])
        elif listing_type == 'internship':
            internships = filter_by_location(internships, country, city)
            for form_field, model_field in filter_fields:
                value = filters.cleaned_data[form_field]
                if value:
                    internships = internships.filter(**{model_field: value})
        elif listing_type == 'resume':
            resumes = filter_by_location(resumes, country, city)
            resume_filter_fields = (
                ('status', 'status'),
                ('working_condition', 'wanted_working_condition'),
                ('work_schedule_and_working_hours', 'wanted_work_schedule_and_working_hours'),
            )
            for form_field, model_field in resume_filter_fields:
                value = filters.cleaned_data[form_field]
                if value:
                    resumes = resumes.filter(**{model_field: value})
            if filters.cleaned_data['salary_min'] is not None:
                resumes = resumes.filter(wanted_salary__gte=filters.cleaned_data['salary_min'])
            if filters.cleaned_data['salary_max'] is not None:
                resumes = resumes.filter(wanted_salary__lte=filters.cleaned_data['salary_max'])

    jobs = annotate_listing_engagement(jobs, request.user).order_by('-created_at')
    internships = annotate_listing_engagement(internships, request.user).order_by('-created_at')
    resumes = annotate_listing_engagement(resumes, request.user).order_by('-created_at')

    page_size = 20 if listing_type else 9
    jobs_page = Paginator(jobs, page_size).get_page(request.GET.get('page') or request.GET.get('jobs_page'))
    internships_page = Paginator(internships, page_size).get_page(request.GET.get('page') or request.GET.get('internships_page'))
    resumes_page = Paginator(resumes, page_size).get_page(request.GET.get('page') or request.GET.get('resumes_page'))
    max_pages = 9

    return {
        'jobs': jobs_page,
        'internships': internships_page,
        'resumes': resumes_page,
        'jobs_page_numbers': get_page_numbers(jobs_page, max_pages),
        'internships_page_numbers': get_page_numbers(internships_page, max_pages),
        'resumes_page_numbers': get_page_numbers(resumes_page, max_pages),
        'max_pages': max_pages,
        'job_count': Job.objects.count(),
        'internship_count': Internship.objects.count(),
        'resume_count': Resume.objects.count(),
        'search_query': search_query,
        'listing_type': listing_type,
        'filters': filters,
        'salary_slider_max': salary_slider_max,
    }


def home_view(request):
    return render(request, 'mainapp/index.html', build_homepage_context(request))


def jobs_page(request):
    return category_page(request, 'job')


def internships_page(request):
    return category_page(request, 'internship')


def resumes_page(request):
    return category_page(request, 'resume')


def category_page(request, listing_type):
    context = build_homepage_context(request, listing_type)
    listing_name = {'job': 'jobs', 'internship': 'internships', 'resume': 'resumes'}[listing_type]
    page_obj = context[listing_name]
    context['items'] = page_obj
    context['page_obj'] = page_obj
    context['page_numbers'] = context[f'{listing_name}_page_numbers']
    context['detail_return_to'] = listing_type
    return render(request, 'mainapp/category_list.html', context)


def get_detail_return_url(request):
    return_pages = {
        'home': 'home',
        'job': 'jobs_page',
        'internship': 'internships_page',
        'resume': 'resumes_page',
    }
    page_name = return_pages.get(request.GET.get('return_to'), 'home')
    return reverse(page_name)


def record_listing_view(request, item):
    item_type = ContentType.objects.get_for_model(item, for_concrete_model=False)
    viewer = {}
    if request.user.is_authenticated:
        viewer['user'] = request.user
    else:
        if request.session.session_key is None:
            request.session.create()
        viewer['session_key'] = request.session.session_key

    with transaction.atomic():
        interaction, created = ListingInteraction.objects.get_or_create(
            **viewer,
            content_type=item_type,
            object_id=item.pk,
            defaults={'viewed_at': timezone.now()},
        )
        if created:
            item.__class__.objects.filter(pk=item.pk).update(view_count=F('view_count') + 1)
        elif interaction.viewed_at is None:
            counted = ListingInteraction.objects.filter(
                pk=interaction.pk,
                viewed_at__isnull=True,
            ).update(viewed_at=timezone.now())
            if counted:
                item.__class__.objects.filter(pk=item.pk).update(view_count=F('view_count') + 1)

    item.refresh_from_db(fields=['view_count'])
    interaction.refresh_from_db(fields=['viewed_at', 'liked_at', 'favorited_at'])

    return {
        'listing_type': item._meta.model_name,
        'like_count': item.interactions.filter(liked_at__isnull=False).count(),
        'interaction': interaction,
    }


def build_activity_entries(user, activity):
    timestamp_field = {
        'likes': 'liked_at',
        'views': 'viewed_at',
        'favorites': 'favorited_at',
    }[activity]
    detail_routes = {
        'job': 'job_detail',
        'internship': 'internship_detail',
        'resume': 'resume_detail',
    }
    entries = []
    interactions = ListingInteraction.objects.filter(
        user=user,
        **{f'{timestamp_field}__isnull': False},
    ).select_related('content_type').order_by(f'-{timestamp_field}')
    for interaction in interactions:
        item = interaction.content_object
        if item is None:
            continue
        if isinstance(item, Resume):
            title = f'{item.name} {item.surname}'
            subtitle = item.email
        else:
            title = item.job_title
            subtitle = item.company_name
        entries.append({
            'title': title,
            'subtitle': subtitle,
            'kind': interaction.content_type.model,
            'url': reverse(detail_routes[interaction.content_type.model], args=[item.pk]),
            'timestamp': getattr(interaction, timestamp_field),
        })
    return entries


def job_detail(request, pk):
    job = get_object_or_404(Job.objects.select_related('country', 'city'), pk=pk)
    engagement = record_listing_view(request, job)
    return render(request, 'mainapp/job_detail.html', {
        'item': job,
        'return_url': get_detail_return_url(request),
        **engagement,
    })


def internship_detail(request, pk):
    item = get_object_or_404(Internship.objects.select_related('country', 'city'), pk=pk)
    engagement = record_listing_view(request, item)
    return render(request, 'mainapp/internship_detail.html', {
        'item': item,
        'return_url': get_detail_return_url(request),
        **engagement,
    })


def resume_detail(request, pk):
    item = get_object_or_404(Resume.objects.select_related('country', 'city'), pk=pk)
    engagement = record_listing_view(request, item)
    return render(request, 'mainapp/resume_detail.html', {
        'item': item,
        'return_url': get_detail_return_url(request),
        **engagement,
    })


@login_required
def listing_interaction(request, listing_type, pk, action):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    models_by_type = {
        'job': Job,
        'internship': Internship,
        'resume': Resume,
    }
    model = models_by_type.get(listing_type)
    if model is None or action not in {'like', 'favorite'}:
        return redirect('home')

    item = get_object_or_404(model, pk=pk)
    timestamp_field = 'liked_at' if action == 'like' else 'favorited_at'
    with transaction.atomic():
        interaction, _ = ListingInteraction.objects.get_or_create(
            user=request.user,
            content_type=ContentType.objects.get_for_model(item, for_concrete_model=False),
            object_id=item.pk,
        )
        interaction = ListingInteraction.objects.select_for_update().get(pk=interaction.pk)
        current_value = getattr(interaction, timestamp_field)
        ListingInteraction.objects.filter(pk=interaction.pk).update(
            **{timestamp_field: None if current_value else timezone.now()},
        )
    route_name = {'job': 'job_detail', 'internship': 'internship_detail', 'resume': 'resume_detail'}[listing_type]
    detail_url = reverse(route_name, args=[item.pk])
    next_url = request.POST.get('next', '')
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)

    return_to = request.POST.get('return_to')
    if return_to in {'home', 'job', 'internship', 'resume'}:
        detail_url = f'{detail_url}?return_to={return_to}'
    return redirect(detail_url)


@login_required
def account_activity(request, activity):
    activity_titles = {
        'likes': _('Liked listings'),
        'views': _('Recently viewed'),
        'favorites': _('Favorites'),
    }
    if activity not in activity_titles:
        return redirect('home')
    return render(request, 'mainapp/account_activity.html', {
        'activity': activity,
        'activity_title': activity_titles[activity],
        'entries': build_activity_entries(request.user, activity),
    })


@login_required
def create_listing(request, listing_type):
    form_config = {
        'job': (JobForm, _('Job'), 'job_detail'),
        'internship': (InternshipForm, _('Internship'), 'internship_detail'),
        'resume': (ResumeForm, _('Resume'), 'resume_detail'),
    }
    form_class, listing_title, detail_url = form_config.get(listing_type, (None, None, None))
    if form_class is None:
        return redirect('home')

    if not can_create_listing(request.user, listing_type):
        return redirect('home')

    form = form_class(request.POST or None, request.FILES or None)
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
    return render(request, 'mainapp/auth.html', {'form': form, 'auth_title': _('Register')})


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
    return render(request, 'mainapp/auth.html', {'form': form, 'auth_title': _('Login')})


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
        request.FILES or None,
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

    if request.method == 'POST' and request.POST.get('action') == 'delete_listing':
        item.delete()
        return redirect('my_listings')

    form = form_class(request.POST or None, request.FILES or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect(detail_url, pk=item.pk)
    return render(request, 'mainapp/create.html', {
        'form': form,
        'listing_title': _('Edit %(listing_type)s') % {'listing_type': listing_type.title()},
        'listing_type': listing_type,
        'item': item,
    })


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

    jobs = Paginator(
        Job.objects.select_related('owner').order_by('-created_at'), 10
    ).get_page(request.GET.get('jobs_page'))
    internships = Paginator(
        Internship.objects.select_related('owner').order_by('-created_at'), 10
    ).get_page(request.GET.get('internships_page'))
    resumes = Paginator(
        Resume.objects.select_related('owner').order_by('-created_at'), 10
    ).get_page(request.GET.get('resumes_page'))

    def page_links(page, page_parameter):
        links = {}
        if page.has_previous():
            query_params = request.GET.copy()
            query_params[page_parameter] = page.previous_page_number()
            links['previous'] = f'?{query_params.urlencode()}'
        if page.has_next():
            query_params = request.GET.copy()
            query_params[page_parameter] = page.next_page_number()
            links['next'] = f'?{query_params.urlencode()}'
        return links

    return render(request, 'mainapp/super_admin.html', {
        'users': users,
        'jobs': jobs,
        'internships': internships,
        'resumes': resumes,
        'job_page_links': page_links(jobs, 'jobs_page'),
        'internship_page_links': page_links(internships, 'internships_page'),
        'resume_page_links': page_links(resumes, 'resumes_page'),
        'search_query': search_query,
        'user_form': user_form,
        'selected_user': selected_user,
    })


@login_required
def super_admin_edit_listing(request, listing_type, pk):
    if not is_super_admin(request.user):
        return super_admin_forbidden(request)

    config = {
        'job': (Job, JobForm, _('Job')),
        'internship': (Internship, InternshipForm, _('Internship')),
        'resume': (Resume, ResumeForm, _('Resume')),
    }
    model, form_class, title = config.get(listing_type, (None, None, None))
    if model is None:
        return redirect('super_admin')
    item = get_object_or_404(model, pk=pk)
    form = form_class(request.POST or None, request.FILES or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('super_admin')
    return render(request, 'mainapp/create.html', {
        'form': form,
        'listing_title': _('Edit %(listing_type)s') % {'listing_type': title},
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

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record_listing_view(request, instance)
        return super().retrieve(request, *args, **kwargs)

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
    filterset_fields = ['country', 'city', 'company_name', 'salary', 'required_experience', 'work_time', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'status']


class ResumeViewSet(OwnerModelViewSet):
    queryset = Resume.objects.all().order_by('-created_at', '-pk')
    serializer_class = ResumeSerializer
    pagination_class = ResumePagination
    throttle_classes = [ResumeThrottle]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['name', 'surname', 'email', 'phone_number', 'experience', 'wanted_salary', 'wanted_working_condition', 'wanted_work_schedule_and_working_hours', 'owner__username', 'owner__account_profile__display_name']
    filterset_fields = ['country', 'city', 'name', 'surname', 'email', 'phone_number', 'phone_number2', 'experience', 'wanted_salary', 'wanted_work_time', 'wanted_working_condition', 'wanted_work_schedule_and_working_hours']


class InternshipViewSet(OwnerModelViewSet):
    queryset = Internship.objects.all().order_by('-created_at', '-pk')
    serializer_class = InternshipSerializer
    pagination_class = InternshipPagination
    throttle_classes = [InternshipThrottle]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    search_fields = ['company_name', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field', 'status', 'owner__username', 'owner__account_profile__display_name']
    filterset_fields = ['country', 'city', 'company_name', 'work_time', 'work_duration', 'job_title', 'working_condition', 'work_schedule_and_working_hours', 'work_field']


class CityListAPIView(APIView):
    """GET /api/cities/?country=<id>[&q=<text>][&limit=50] -> [{"id": 1, "name": "..."}].

    * ``name`` is in the active language (Accept-Language / language cookie), falling back to the English name.
    * ``q`` is a case-, accent- and apostrophe-insensitive search in the names of all languages
      (Koeln = Köln, Qo'qon = Qoqon, ташкент = Ташкент); names starting with ``q`` come first.
    * Ordering: by population (biggest first), then by name. ``limit`` defaults to 50, at most 100.

    Public reference data (no personal data), so no authentication; protected by its own throttle.
    A missing country gives an empty list (the dependent field simply stays empty).
    """

    permission_classes = [permissions.AllowAny]
    throttle_classes = [CityThrottle]
    default_limit = 50
    max_limit = 100

    def get(self, request):
        raw_country = request.query_params.get('country', '').strip()
        if not raw_country:
            return Response([])
        try:
            country_id = int(raw_country)
        except ValueError:
            return Response({'detail': 'country must be an integer id.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            limit = int(request.query_params.get('limit', self.default_limit))
        except ValueError:
            return Response({'detail': 'limit must be an integer.'}, status=status.HTTP_400_BAD_REQUEST)
        limit = max(1, min(limit, self.max_limit))

        cities = City.objects.filter(country_id=country_id).order_by('-population', 'name')
        query = normalize_search(request.query_params.get('q', ''))
        if query:
            cities = cities.filter(search_text__contains=query)
            # Take a wider slice so that prefix matches can be moved to the top before cutting to `limit`.
            rows = list(cities[: max(limit * 4, 200)])
            rows.sort(key=lambda city: not any(part.startswith(query) for part in city.search_text.split('|')))
        else:
            rows = list(cities[:limit])
        language = get_language()
        return Response([{'id': city.pk, 'name': city.get_localized_name(language)} for city in rows[:limit]])


PASSWORD_RESET_THROTTLE_SESSION_KEY = 'password_reset_throttle_notice'


class ThrottledPasswordResetView(auth_views.PasswordResetView):
    """PasswordResetView limited to one email per address / N requests per IP per window.

    The check does not depend on whether the account exists, and the redirect target is the same
    password_reset_done page, so the response never reveals whether an email is registered.
    """

    def form_valid(self, form):
        email = form.cleaned_data['email'].strip().lower()
        client_ip = ratelimit.get_client_ip(self.request)
        retry_after = 0
        notice = None

        # IP limit first, so a blocked IP does not consume the per-email slot. It is skipped when no
        # real client address is available (e.g. REMOTE_ADDR is the platform proxy and
        # TRUSTED_PROXY_COUNT is not configured) to avoid locking everybody out through a shared bucket.
        if ratelimit.is_public_ip(client_ip):
            allowed, retry_after = ratelimit.hit(
                'pwreset-ip', client_ip, settings.PASSWORD_RESET_IP_LIMIT, settings.PASSWORD_RESET_IP_WINDOW,
            )
            if not allowed:
                notice = 'ip'
        if notice is None:
            allowed, retry_after = ratelimit.hit(
                'pwreset-email', email, 1, settings.PASSWORD_RESET_EMAIL_COOLDOWN,
            )
            if not allowed:
                notice = 'email'

        if notice:
            self.request.session[PASSWORD_RESET_THROTTLE_SESSION_KEY] = {
                'kind': notice,
                'minutes': max(1, -(-retry_after // 60)),
            }
            return HttpResponseRedirect(self.get_success_url())
        ratelimit.purge_stale()
        return super().form_valid(form)


class ThrottledPasswordResetDoneView(auth_views.PasswordResetDoneView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        info = self.request.session.pop(PASSWORD_RESET_THROTTLE_SESSION_KEY, None)
        if info:
            if info['kind'] == 'ip':
                template = gettext('Too many reset requests. Please try again in %(minutes)d min.')
            else:
                template = gettext('A reset email has already been sent. You can request another in %(minutes)d min.')
            context['throttle_notice'] = template % {'minutes': info['minutes']}
        return context
