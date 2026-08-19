"""Cron: 5 20 * * *  python manage.py process_attendance"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.utils import now as app_now, today as app_today

from apps.attendance.services import mark_absentees, rebuild_range


class Command(BaseCommand):
    help = "Rebuild DailyAttendance from punch logs and mark absentees."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="YYYY-MM-DD (default: today)")
        parser.add_argument("--days", type=int, default=1, help="How many days back to process")

    def handle(self, *args, **options):
        if options.get("date"):
            end = datetime.strptime(options["date"], "%Y-%m-%d").date()
        else:
            end = app_today()
        start = end - timedelta(days=options["days"] - 1)
        count = rebuild_range(start, end)
        day = start
        while day <= end:
            mark_absentees(day)
            day += timedelta(days=1)
        self.stdout.write(self.style.SUCCESS(f"{start} to {end}: {count} records processed."))
