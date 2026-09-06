"""Taking someone off the system when they leave.

Deactivating an employee has to do three separate things, and missing any one
of them leaves a hole:

  * stop them signing in - including any session they already have open, which
    Django does not end on its own;
  * stop the attendance engine counting them, so a person who left in June does
    not quietly accumulate absences for the rest of the year;
  * keep every record they made while they worked here, because attendance,
    leave and task history is what payroll and any later dispute rely on.

Nothing is ever deleted. Leaving is a state, not an erasure.
"""
from __future__ import annotations

from django.contrib.sessions.models import Session
from django.utils import timezone


def end_all_sessions(user) -> int:
    """Sign the person out everywhere they are currently signed in.

    Django checks `is_active` when someone logs in, but not on later requests,
    so without this a deactivated employee keeps working in an open tab.
    """
    ended = 0
    for session in Session.objects.iterator():
        data = session.get_decoded()
        if str(data.get("_auth_user_id")) == str(user.pk):
            session.delete()
            ended += 1
    return ended


def deactivate_employee(user, *, by=None, exit_date=None, reason="", note="",
                        cancel_pending=True):
    """Mark an employee as having left, and close off their access."""
    from apps.attendance.models import DailyAttendance, HomeOfficeEntry
    from apps.leaves.models import LeaveRequest
    from apps.utils import today

    exit_date = exit_date or today()

    user.is_active = False
    user.is_attendance_tracked = False
    user.exit_date = exit_date
    user.exit_reason = reason or ""
    user.exit_note = note or ""
    user.deactivated_at = timezone.now()
    user.deactivated_by = by
    user.save()

    sessions_ended = end_all_sessions(user)

    # Days after the last working day were never worked, so an absence there
    # would be wrong. Anything with a real punch on it is left alone.
    removed = DailyAttendance.objects.filter(
        employee=user, date__gt=exit_date, check_in__isnull=True
    ).delete()[0]

    cancelled = 0
    if cancel_pending:
        cancelled = LeaveRequest.objects.filter(
            employee=user, status=LeaveRequest.Status.PENDING
        ).update(status=LeaveRequest.Status.CANCELLED)
        HomeOfficeEntry.objects.filter(
            employee=user, date__gt=exit_date, status=HomeOfficeEntry.Status.PENDING
        ).update(status=HomeOfficeEntry.Status.REJECTED)

    return {
        "sessions_ended": sessions_ended,
        "future_days_removed": removed,
        "requests_cancelled": cancelled,
    }


def reactivate_employee(user, *, by=None, track_attendance=True):
    """Someone rejoined, or the deactivation was a mistake."""
    user.is_active = True
    user.is_attendance_tracked = track_attendance
    user.exit_date = None
    user.exit_reason = ""
    user.exit_note = ""
    user.deactivated_at = None
    user.deactivated_by = None
    user.save()
    return user
