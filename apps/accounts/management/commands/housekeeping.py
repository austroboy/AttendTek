"""Nightly tidy-up.  Cron:  40 21 * * *  python manage.py housekeeping"""
from django.core.management.base import BaseCommand

from apps.accounts.throttle import prune


class Command(BaseCommand):
    help = "Clears out records that only matter for a few days."

    def handle(self, *args, **options):
        removed = prune(days=7)
        self.stdout.write(self.style.SUCCESS(f"{removed} old login attempt(s) cleared."))
