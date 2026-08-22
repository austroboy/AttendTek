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

Punches through the day are paired odd/even: the 1st, 3rd, 5th ... punch is an
IN and the 2nd, 4th, 6th ... is an OUT. Everything between an OUT and the next
IN is a trip out of the office. Trips on office work still count as working
time; personal trips do not, and they push the required out time back by the
same amount.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timedelta

from .models import DailyAttendance

Status = DailyAttendance.Status


def _minutes(delta: timedelta) -> int:
    return max(0, int(round(delta.total_seconds() / 60)))


@dataclass
class DaySegments:
    """The shape of one day, worked out from its punches."""

    punches: list[datetime] = field(default_factory=list)      # after removing duplicate taps
    ignored: list[datetime] = field(default_factory=list)      # the duplicates we dropped
    check_in: datetime | None = None
    check_out: datetime | None = None
    sessions: list[tuple[datetime, datetime | None]] = field(default_factory=list)
    trips: list[tuple[datetime, datetime]] = field(default_factory=list)
    inside_minutes: int = 0

    @property
    def open_session(self) -> bool:
        """True when the last punch was an IN, so the day has no closing OUT."""
        return len(self.punches) % 2 == 1

    def direction_of(self, punch_time: datetime) -> str:
        """IN for the odd punches of the day, OUT for the even ones."""
        try:
            index = self.punches.index(punch_time)
        except ValueError:
            return "UNKNOWN"
        return "IN" if index % 2 == 0 else "OUT"


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
    inside_minutes: int = 0
    outside_minutes: int = 0
    outside_paid_minutes: int = 0
    outside_unpaid_minutes: int = 0
    trip_count: int = 0
    is_late: bool = False
    is_early_out: bool = False
    remarks: list[str] = field(default_factory=list)

    @property
    def remark_text(self) -> str:
        return " | ".join(self.remarks)[:200]


def required_out_time(shift, day: date_cls, check_in: datetime, unpaid_minutes: int = 0) -> datetime:
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
        base = scheduled_out
    else:
        base = max(scheduled_out, check_in + shift.required_delta)
    # Time spent out of the office on personal errands has to be made up.
    return base + timedelta(minutes=unpaid_minutes)


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
    inside_minutes: int | None = None,
    outside_paid_minutes: int = 0,
    outside_unpaid_minutes: int = 0,
    trip_count: int = 0,
) -> Evaluation:
    """Work out one day's result.

    inside_minutes / outside_* come from build_segments(). When they are not
    given the day is treated as a simple in-and-out with nothing in between.
    """
    ev = Evaluation(check_in=check_in, check_out=check_out)
    ev.outside_paid_minutes = outside_paid_minutes
    ev.outside_unpaid_minutes = outside_unpaid_minutes
    ev.outside_minutes = outside_paid_minutes + outside_unpaid_minutes
    ev.trip_count = trip_count

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
    ev.required_out = required_out_time(shift, day, check_in, outside_unpaid_minutes)

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

    if outside_unpaid_minutes:
        ev.remarks.append(
            f"{outside_unpaid_minutes} min out of office on personal time, "
            f"so the required out time moved to {ev.required_out:%I:%M %p}"
        )

    if not check_out:
        ev.status = Status.MISSING_OUT
        ev.inside_minutes = inside_minutes or 0
        ev.shortfall_minutes = _minutes(shift.required_delta)
        ev.remarks.append("No out punch recorded")
        return ev

    if inside_minutes is None:
        # No breakdown available: treat the whole span as time worked.
        ev.inside_minutes = _minutes(check_out - check_in)
    else:
        ev.inside_minutes = inside_minutes

    # Office errands still count; personal time does not.
    ev.worked_minutes = ev.inside_minutes + outside_paid_minutes
    worked = timedelta(minutes=ev.worked_minutes)

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

    if trip_count:
        ev.remarks.insert(
            0,
            f"{trip_count} trip{'s' if trip_count > 1 else ''} out of the office "
            f"({ev.outside_minutes} min total)",
        )
    if mode == DailyAttendance.Mode.HOME:
        ev.remarks.insert(0, "Home office")
    return ev


def drop_duplicate_taps(punch_times: list[datetime], window_minutes: int):
    """Collapse punches that land within `window_minutes` of the one before.

    People often tap the reader twice - once because it did not beep, once to
    be sure. Those are the same event, not an exit.
    """
    kept: list[datetime] = []
    dropped: list[datetime] = []
    window = timedelta(minutes=window_minutes)
    for t in sorted(punch_times):
        if kept and t - kept[-1] < window:
            dropped.append(t)
        else:
            kept.append(t)
    return kept, dropped


def build_segments(punch_times: list[datetime], shift) -> DaySegments:
    """Turn a day's punches into in-office sessions and trips outside.

    punch 1 = IN, punch 2 = OUT, punch 3 = IN, punch 4 = OUT ...
    so (1,2) and (3,4) are time inside, and (2,3) is a trip out.
    """
    seg = DaySegments()
    if not punch_times:
        return seg

    kept, dropped = drop_duplicate_taps(punch_times, shift.duplicate_window_minutes)
    seg.punches, seg.ignored = kept, dropped
    seg.check_in = kept[0]

    # An even number of punches means the day was closed with an OUT.
    seg.check_out = kept[-1] if len(kept) >= 2 and len(kept) % 2 == 0 else None

    # Sessions inside the office: punches taken two at a time.
    for i in range(0, len(kept) - 1, 2):
        start, end = kept[i], kept[i + 1]
        seg.sessions.append((start, end))
        seg.inside_minutes += _minutes(end - start)
    if seg.open_session:
        seg.sessions.append((kept[-1], None))

    # Trips outside: the gaps between one OUT and the next IN.
    min_trip = timedelta(minutes=shift.min_outing_minutes)
    for i in range(1, len(kept) - 1, 2):
        left, back = kept[i], kept[i + 1]
        if back - left >= min_trip:
            seg.trips.append((left, back))
        else:
            # Too short to be a real trip - treat it as time inside.
            seg.inside_minutes += _minutes(back - left)
    return seg


def pick_in_out(punch_times: list[datetime], shift) -> tuple[datetime | None, datetime | None]:
    """Kept for older callers - the first and last punch of the day."""
    seg = build_segments(punch_times, shift)
    return seg.check_in, seg.check_out
