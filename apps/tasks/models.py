from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.utils import now as app_now, today as app_today


class DailyTask(models.Model):
    """What each employee worked on, logged day by day."""

    class Progress(models.TextChoices):
        DONE = "DONE", "Done"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        BLOCKED = "BLOCKED", "Blocked"

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="daily_tasks"
    )
    date = models.DateField(default=app_today)
    title = models.CharField(max_length=160)
    details = models.TextField(blank=True)
    project = models.CharField(max_length=80, blank=True)
    minutes_spent = models.PositiveIntegerField(
        default=60, help_text="How long the task took, stored in minutes"
    )
    progress = models.CharField(max_length=12, choices=Progress.choices, default=Progress.DONE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.employee.display_name} - {self.date:%d %b} - {self.title}"

    @property
    def badge_class(self):
        return {"DONE": "ok", "IN_PROGRESS": "info", "BLOCKED": "bad"}[self.progress]

    @property
    def hours(self):
        return self.minutes_spent // 60

    @property
    def minutes(self):
        return self.minutes_spent % 60

    @property
    def duration_display(self):
        """1h 05m, or just 45m for anything under an hour."""
        if self.minutes_spent < 60:
            return f"{self.minutes_spent}m"
        if self.minutes:
            return f"{self.hours}h {self.minutes:02d}m"
        return f"{self.hours}h"

    @property
    def was_edited(self):
        """True once the entry has been changed after it was first logged."""
        if not (self.created_at and self.updated_at):
            return False
        return (self.updated_at - self.created_at).total_seconds() > 60

    @property
    def is_open(self):
        return self.progress != self.Progress.DONE

    @staticmethod
    def format_minutes(total):
        total = int(total or 0)
        if total < 60:
            return f"{total}m"
        h, m = divmod(total, 60)
        return f"{h}h {m:02d}m" if m else f"{h}h"
