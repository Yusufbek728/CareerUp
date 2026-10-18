import hashlib
import ipaddress
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import RateLimitCounter


def hit(scope, raw_key, limit, window_seconds):
    """Register one attempt. Returns (allowed, retry_after_seconds).

    Fixed window stored in the DB, so the counter is shared between gunicorn workers and
    instances (LocMemCache is per-process). The increment is a single conditional UPDATE
    (`count < limit`), so concurrent requests cannot both slip through the limit.
    """
    key = hashlib.sha256(str(raw_key).encode('utf-8')).hexdigest()
    now = timezone.now()
    cutoff = now - timedelta(seconds=window_seconds)
    with transaction.atomic():
        # Start a fresh window if the previous one has expired.
        RateLimitCounter.objects.filter(scope=scope, key=key, window_start__lte=cutoff).update(
            window_start=now, count=0,
        )
        counter, _created = RateLimitCounter.objects.get_or_create(
            scope=scope, key=key, defaults={'window_start': now, 'count': 0},
        )
        updated = RateLimitCounter.objects.filter(pk=counter.pk, count__lt=limit).update(count=F('count') + 1)
    if updated:
        return True, 0
    counter.refresh_from_db()
    elapsed = (now - counter.window_start).total_seconds()
    return False, max(1, int(window_seconds - elapsed))


def purge_stale(max_age_seconds=86400):
    RateLimitCounter.objects.filter(window_start__lt=timezone.now() - timedelta(seconds=max_age_seconds)).delete()


def get_client_ip(request):
    """Client IP that is safe against X-Forwarded-For spoofing.

    By default only REMOTE_ADDR is used. If the app sits behind N trusted proxies
    (settings.TRUSTED_PROXY_COUNT), the entry N-th from the right of X-Forwarded-For is used:
    that is the address the outermost trusted proxy saw. Entries to its left are client-controlled
    and are ignored.
    """
    remote = request.META.get('REMOTE_ADDR', '')
    proxies = getattr(settings, 'TRUSTED_PROXY_COUNT', 0)
    if proxies > 0:
        parts = [p.strip() for p in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if p.strip()]
        if len(parts) >= proxies:
            return parts[-proxies]
    return remote


def is_public_ip(value):
    """False for invalid/private/loopback addresses (e.g. the proxy itself on Render)."""
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False
