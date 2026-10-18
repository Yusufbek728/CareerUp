from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.contrib.auth.models import User
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import F, Value
from django.db.models.functions import Coalesce, NullIf
from django.utils.translation import get_language, gettext_lazy as _

from .geo_utils import build_search_text, flag_emoji, language_key

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


class LocalizedNameMixin:
    """``name`` is the canonical (English) name; name_en/name_ru/name_uz are display names per language."""

    def get_localized_name(self, language=None):
        key = language_key(language or get_language())
        return getattr(self, f'name_{key}', '') or self.name

    @property
    def localized_name(self):
        return self.get_localized_name()

    def __str__(self):
        return self.localized_name


class CountryQuerySet(models.QuerySet):
    def localized(self, language=None):
        """Featured countries first, then alphabetically by the name in the active language."""
        key = language_key(language or get_language())
        return self.annotate(
            sort_name=Coalesce(NullIf(F(f'name_{key}'), Value('')), F('name')),
        ).order_by('-priority', 'sort_name', 'pk')


class Country(LocalizedNameMixin, models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=2, unique=True, null=True, blank=True, help_text=_('ISO 3166-1 alpha-2'))
    name_en = models.CharField(max_length=100, blank=True, default='')
    name_ru = models.CharField(max_length=100, blank=True, default='')
    name_uz = models.CharField(max_length=100, blank=True, default='')
    priority = models.SmallIntegerField(default=0, help_text=_('Higher values are listed first.'))

    objects = CountryQuerySet.as_manager()

    class Meta:
        ordering = ['-priority', 'name']
        verbose_name = _('country')
        verbose_name_plural = _('countries')

    @property
    def flag(self):
        return flag_emoji(self.code)

    @property
    def display_name(self):
        """'🇺🇿 Oʻzbekiston' - used in selects and on cards."""
        return f'{self.flag} {self.localized_name}'.strip()


class City(LocalizedNameMixin, models.Model):
    country = models.ForeignKey(Country, on_delete=models.CASCADE, related_name='cities')
    name = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150, blank=True, default='')
    name_ru = models.CharField(max_length=150, blank=True, default='')
    name_uz = models.CharField(max_length=150, blank=True, default='')
    population = models.PositiveBigIntegerField(default=0, db_index=True)
    geoname_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    # Normalized names of all languages joined with '|': case/accent-insensitive search on any database
    # (SQLite's LIKE ignores case for ASCII only). Filled in save() and by the geo seeding code.
    search_text = models.TextField(blank=True, default='', editable=False)

    class Meta:
        ordering = ['-population', 'name']
        verbose_name = _('city')
        verbose_name_plural = _('cities')
        constraints = [
            models.UniqueConstraint(fields=['country', 'name'], name='unique_city_name_per_country'),
        ]

    def save(self, *args, **kwargs):
        self.search_text = build_search_text(self.name, self.name_en, self.name_ru, self.name_uz)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = {*update_fields, 'search_text'}
        super().save(*args, **kwargs)


def check_city_belongs_to_country(country, city):
    """Shared by forms and DRF serializers: a city requires a country and must belong to it."""
    if city is None:
        return
    if country is None:
        raise ValidationError(_('Select a country first.'), code='country_required')
    if city.country_id != country.pk:
        raise ValidationError(_('The selected city does not belong to the selected country.'), code='city_country_mismatch')


def format_location(city, country):
    """'Toshkent, Oʻzbekiston' (names in the active language) / only the country / empty string."""
    return ', '.join(str(part) for part in (city, country) if part)


def format_location_with_flag(city, country):
    """Same as format_location, prefixed with the country flag emoji."""
    location = format_location(city, country)
    flag = country.flag if country else ''
    return f'{flag} {location}'.strip() if location else ''


def country_fk(related_name):
    return models.ForeignKey(Country, on_delete=models.SET_NULL, null=True, blank=True, related_name=related_name)


def city_fk(related_name):
    return models.ForeignKey(City, on_delete=models.SET_NULL, null=True, blank=True, related_name=related_name)


class Job(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='jobs', null=True, blank=True)
    interactions = GenericRelation('ListingInteraction', related_query_name='job')
    view_count = models.PositiveIntegerField(default=0)
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
    country = country_fk('jobs')
    city = city_fk('jobs')

    @property
    def location(self):
        return format_location(self.city, self.country)

    @property
    def location_with_flag(self):
        return format_location_with_flag(self.city, self.country)

    def save(self, *args, **kwargs):
        self.hourly_income = Decimal(self.salary) / Decimal(self.work_time) if self.work_time else 0
        super().save(*args, **kwargs)

    def __str__(self):
        return self.job_title

class Internship(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='internships', null=True, blank=True)
    interactions = GenericRelation('ListingInteraction', related_query_name='internship')
    view_count = models.PositiveIntegerField(default=0)
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
    country = country_fk('internships')
    city = city_fk('internships')

    @property
    def location(self):
        return format_location(self.city, self.country)

    @property
    def location_with_flag(self):
        return format_location_with_flag(self.city, self.country)

    def __str__(self):
        return self.job_title

class Resume(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='resumes', null=True, blank=True)
    interactions = GenericRelation('ListingInteraction', related_query_name='resume')
    view_count = models.PositiveIntegerField(default=0)
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
    country = country_fk('resumes')
    city = city_fk('resumes')

    @property
    def location(self):
        return format_location(self.city, self.country)

    @property
    def location_with_flag(self):
        return format_location_with_flag(self.city, self.country)

    @property
    def wanted_hourly_income(self):
        if not self.wanted_work_time:
            return Decimal('0.00')
        return (Decimal(self.wanted_salary) / Decimal(self.wanted_work_time)).quantize(Decimal('0.01'))


class ListingInteraction(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='listing_interactions',
        blank=True,
        null=True,
    )
    session_key = models.CharField(max_length=40, blank=True, null=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    liked_at = models.DateTimeField(blank=True, null=True)
    favorited_at = models.DateTimeField(blank=True, null=True)
    viewed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('user', 'content_type', 'object_id'),
                condition=models.Q(user__isnull=False),
                name='unique_user_listing_interaction',
            ),
            models.UniqueConstraint(
                fields=('session_key', 'content_type', 'object_id'),
                condition=models.Q(session_key__isnull=False),
                name='unique_session_listing_interaction',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, session_key__isnull=True)
                    | models.Q(user__isnull=True, session_key__isnull=False)
                ),
                name='listing_interaction_has_one_viewer',
            ),
        ]

class RateLimitCounter(models.Model):
    """Fixed-window counter shared by all workers/instances (stored in the main DB).

    One row per (scope, key). `key` is a sha256 hex digest, so raw emails are not stored.
    Used to throttle password-reset emails (see mainapp/ratelimit.py).
    """

    scope = models.CharField(max_length=32)
    key = models.CharField(max_length=64)
    window_start = models.DateTimeField(db_index=True)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['scope', 'key'], name='unique_ratelimit_scope_key'),
        ]

    def __str__(self):
        return f'{self.scope}:{self.key[:8]} ({self.count})'
