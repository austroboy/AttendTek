"""Attendance rule engine.

Office policy (all values come from the Shift model):
  * Office hours: 9:00 AM - 6:00 PM  => 9 hours
  * A punch after 10:00 AM is LATE
  * The 9 hours must still be completed:
        required_out = max(6:00 PM, check_in + 9 hours)
    so an in-punch at 10:02 AM means leaving at 7:02 PM.
  * Leaving before required_out is an EARLY OUT
    (late and early out together give the status LATE_EARLY)
  * Working past required_out is overtime; less than the required
    hours is a shortfall.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timedelta

from .models import DailyAttendance

Status = DailyAttendance.Status


def _minutes(delta: timedelta) -> int:
    return max(0, int(round(delta.total_seconds() / 60)))


@dataclass
class Evaluation:
    status: str = Status.ABSENT
    check_in: datetime | None = None
    check_out: datetime | None = None
    required_out: datetime | None = None
    worked_minutes: int = 0
    late_minutes: int = 0
    early_out_minutes: int = 0
    overtime_minutes: int = 0
    shortfall_minutes: int = 0
    is_late: bool = False
    is_early_out: bool = False
    remarks: list[str] = field(default_factory=list)

    @property
    def remark_text(self) -> str:
        return " | ".join(self.remarks)[:200]


def required_out_time(shift, day: date_cls, check_in: datetime) -> datetime:
    """When the employee must leave to complete the required hours.

    Default: max(office end, in + required hours)
      - 9:00 AM in  -> 6:00 PM
      - 10:02 AM in -> 7:02 PM
      - in at 9:45 AM  -> 6:45 PM  (the full 9 hours are always required)
    Shift.extend_only_when_late = True korle grace period er bhitore
    keeps the normal 6:00 PM end time for anyone inside the grace period.
    """
    scheduled_out = datetime.combine(day, shift.end_time)
    late_cutoff = datetime.combine(day, shift.late_after)
    if shift.extend_only_when_late and check_in <= late_cutoff:
        return scheduled_out
    return max(scheduled_out, check_in + shift.required_delta)


def evaluate_day(
    shift,
    day: date_cls,
    check_in: datetime | None,
    check_out: datetime | None,
    *,
    mode: str = DailyAttendance.Mode.OFFICE,
    is_holiday: bool = False,
    is_on_leave: bool = False,
    punch_count: int = 0,
) -> Evaluation:
    ev = Evaluation(check_in=check_in, check_out=check_out)

    # --- handle non-working days first ---
    if is_on_leave and not check_in:
        ev.status = Status.LEAVE
        ev.remarks.append("Approved leave")
        return ev
    if is_holiday and not check_in:
        ev.status = Status.HOLIDAY
        return ev
    if shift.is_weekend(day) and not check_in:
        ev.status = Status.WEEKEND
        return ev
    if not check_in:
        ev.status = Status.ABSENT
        ev.shortfall_minutes = _minutes(shift.required_delta)
        return ev

    # --- working day ---
    scheduled_in = datetime.combine(day, shift.start_time)
    late_cutoff = datetime.combine(day, shift.late_after)
    ev.required_out = required_out_time(shift, day, check_in)

    if check_in > late_cutoff:
        ev.is_late = True
        ev.late_minutes = _minutes(check_in - scheduled_in)
        ev.remarks.append(
            f"Punched in at {check_in:%I:%M %p}, after the "
            f"{shift.late_after:%I:%M %p} cut-off, so the required out time "
            f"is {ev.required_out:%I:%M %p}"
        )
    elif check_in > scheduled_in:
        # inside the grace period: not late, but we still record the minutes
        ev.late_minutes = _minutes(check_in - scheduled_in)

    if not check_out:
        ev.status = Status.MISSING_OUT
        ev.shortfall_minutes = _minutes(shift.required_delta)
        ev.remarks.append("No out punch recorded")
        return ev

    worked = check_out - check_in
    ev.worked_minutes = _minutes(worked)

    if check_out < ev.required_out:
        ev.is_early_out = True
        ev.early_out_minutes = _minutes(ev.required_out - check_out)
    else:
        ev.overtime_minutes = _minutes(check_out - ev.required_out)

    if worked < shift.required_delta:
        ev.shortfall_minutes = _minutes(shift.required_delta - worked)

    # --- final status ---
    if worked < shift.half_day_delta:
        ev.status = Status.HALF_DAY
        ev.remarks.append("Half day (under the half-day threshold)")
    elif ev.is_late and ev.is_early_out:
        ev.status = Status.LATE_EARLY
    elif ev.is_late:
        ev.status = Status.LATE
    elif ev.is_early_out:
        ev.status = Status.EARLY_OUT
        ev.remarks.append(f"Left before the required out time of {ev.required_out:%I:%M %p}")
    else:
        ev.status = Status.PRESENT

    if mode == DailyAttendance.Mode.HOME:
        ev.remarks.insert(0, "Home office")
    return ev


def pick_in_out(punch_times: list[datetime], shift) -> tuple[datetime | None, datetime | None]:
    """From all punches of a day: the first is IN and the last is OUT.

    Two punches closer together than min_out_gap_minutes are treated as a
    double tap on the reader, not as an out punch.
    """
    if not punch_times:
        return None, None
    ordered = sorted(punch_times)
    first = ordered[0]
    gap = timedelta(minutes=shift.min_out_gap_minutes)
    last = None
    for t in reversed(ordered):
        if t - first >= gap:
            last = t
            break
    return first, last
