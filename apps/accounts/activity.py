"""A record of who changed what.

Attendance feeds payroll, so an admin editing a day, approving a correction or
deactivating somebody is a decision that may need explaining months later.
Django keeps no trace of any of it by default. This does - briefly, in plain
words, and without ever getting in the way of the action itself.
"""
from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    class Action(models.TextChoices):
        ATTENDANCE_EDITED = "ATT_EDIT", "Attendance edited"
        CORRECTION_APPROVED = "CORR_OK", "Correction approved"
        CORRECTION_REJECTED = "CORR_NO", "Correction rejected"
        PUNCH_ADDED = "PUNCH_ADD", "Punch added by hand"
        EMPLOYEE_DEACTIVATED = "EMP_OFF", "Employee deactivated"
        EMPLOYEE_REACTIVATED = "EMP_ON", "Employee reactivated"
        LEAVE_DECIDED = "LEAVE", "Leave decided"
        CARD_CHANGED = "CARD", "RFID card changed"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="activity_done",
    )
    action = models.CharField(max_length=12, choices=Action.choices)
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="activity_received",
    )
    subject = models.CharField(max_length=120, blank=True, help_text="Which day or record")
    detail = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"]), models.Index(fields=["action"])]

    def __str__(self):
        return f"{self.get_action_display()} by {self.actor} on {self.created_at:%d %b %Y}"

    @property
    def badge_class(self):
        return {
            self.Action.ATTENDANCE_EDITED: "warn",
            self.Action.CORRECTION_APPROVED: "ok",
            self.Action.CORRECTION_REJECTED: "bad",
            self.Action.PUNCH_ADDED: "info",
            self.Action.EMPLOYEE_DEACTIVATED: "bad",
            self.Action.EMPLOYEE_REACTIVATED: "ok",
            self.Action.LEAVE_DECIDED: "info",
            self.Action.CARD_CHANGED: "muted",
        }.get(self.action, "muted")


def log(actor, action, *, target=None, subject="", detail=""):
    """Write one line to the trail. Never allowed to break the caller."""
    try:
        return ActivityLog.objects.create(
            actor=actor if getattr(actor, "pk", None) else None,
            action=action, target=target,
            subject=subject[:120], detail=detail[:300],
        )
    except Exception:
        # An audit line failing must not stop an admin doing their job.
        return None
