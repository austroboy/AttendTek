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
    hours_spent = models.DecimalField(max_digits=4, decimal_places=2, default=1)
    progress = models.CharField(max_length=12, choices=Progress.choices, default=Progress.DONE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.employee.display_name} - {self.date:%d %b} - {self.title}"

    @property
    def badge_class(self):
        return {"DONE": "ok", "IN_PROGRESS": "info", "BLOCKED": "bad"}[self.progress]
