from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class LeaveType(models.Model):
    name = models.CharField(max_length=60, unique=True)
    code = models.CharField(max_length=10, blank=True)
    annual_quota = models.PositiveSmallIntegerField(default=10, help_text="Days allowed per year")
    is_paid = models.BooleanField(default=True)
    color = models.CharField(max_length=7, default="#3F83F8")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LeaveRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Waiting for approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_requests"
    )
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    start_date = models.DateField()
    end_date = models.DateField()
    is_half_day = models.BooleanField(default=False)
    reason = models.TextField()
    attachment = models.FileField(upload_to="leave-docs/", null=True, blank=True)
    contact_during_leave = models.CharField(max_length=40, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="reviewed_leaves",
    )
    review_note = models.CharField(max_length=200, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.employee.display_name} - {self.leave_type.name} ({self.start_date:%d %b})"

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "The end date cannot be before the start date."})

    @property
    def total_days(self):
        if not (self.start_date and self.end_date):
            return 0
        days = (self.end_date - self.start_date).days + 1
        return 0.5 if self.is_half_day and days == 1 else days

    @property
    def badge_class(self):
        return {"PENDING": "warn", "APPROVED": "ok", "REJECTED": "bad", "CANCELLED": "muted"}[self.status]

    def date_list(self):
        d, out = self.start_date, []
        while d <= self.end_date:
            out.append(d)
            d += timedelta(days=1)
        return out

    def approve(self, by, note=""):
        self.status = self.Status.APPROVED
        self.reviewed_by = by
        self.review_note = note
        self.reviewed_at = timezone.now()
        self.save()
        self._sync_attendance()

    def reject(self, by, note=""):
        self.status = self.Status.REJECTED
        self.reviewed_by = by
        self.review_note = note
        self.reviewed_at = timezone.now()
        self.save()
        self._sync_attendance()

    def _sync_attendance(self):
        from apps.attendance.services import rebuild_day
        for d in self.date_list():
            rebuild_day(self.employee, d)
