import os

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User

from mainapp.models import AccountProfile


class Command(BaseCommand):
    help = 'Create or promote the configured deployment administrator.'

    def handle(self, *args, **options):
        username = os.getenv('SUPER_ADMIN_USERNAME', '').strip()
        password = os.getenv('SUPER_ADMIN_PASSWORD', '')
        display_name = os.getenv('SUPER_ADMIN_DISPLAY_NAME', username)

        if not username or not password:
            raise CommandError(
                'SUPER_ADMIN_USERNAME and SUPER_ADMIN_PASSWORD must be set.'
            )

        user = User.objects.filter(username__iexact=username).first()
        created = user is None
        if created:
            user = User(username=username)

        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        if created:
            user.set_password(password)
        user.save()

        AccountProfile.objects.update_or_create(
            user=user,
            defaults={
                'role': 'company',
                'display_name': display_name,
            },
        )

        action = 'Created' if created else 'Promoted'
        self.stdout.write(self.style.SUCCESS(f'{action} administrator {user.username}.'))
