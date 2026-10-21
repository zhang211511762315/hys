"""Explicit one-time provisioning; never called by application startup."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from agent_runtime.public_workspace import USERNAME


class Command(BaseCommand):
    help = "Provision a public project workspace without granting system-user permissions."

    @transaction.atomic
    def handle(self, *args, **options):
        user, created = get_user_model().objects.get_or_create(username=USERNAME, defaults={'is_active': True, 'is_staff': True})
        if user.is_superuser or not user.is_active:
            raise CommandError('existing workspace identity has unexpected privileges/state')
        user.is_staff = True
        user.set_unusable_password()
        user.save(update_fields=['is_staff', 'password'])
        user.groups.clear()
        user.user_permissions.set(Permission.objects.filter(content_type__app_label__in=['aggregator', 'agent_runtime']))
        self.stdout.write('public workspace ready; system-user permissions absent')
