"""Service layer that turns punch logs into DailyAttendance records."""
from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta

from django.db import transaction
from django.db.models import Q

from apps.accounts.models import Shift, User
from apps.leaves.models import LeaveRequest

from .models import DailyAttendance, Holiday, HomeOfficeEntry, Outing, PunchLog
from .rules import build_segments, evaluate_day


def match_employee(card_no: str = "", device_user_id: str = "") -> User | None:
    """Find the employee behind a card number or device user id."""
    q = Q(pk__isnull=True)
    if card_no:
        q |= Q(rfid_card_no__iexact=str(card_no).strip())
    if device_user_id:
        q |= Q(device_user_id=str(device_user_id).strip())
    return User.objects.filter(q).first()


def record_punch(
    *, employee=None, punch_time: datetime, card_no="", device_user_id="",
    device=None, source=PunchLog.Source.DEVICE, raw_status=0, note="",
) -> tuple[PunchLog | None, bool]:
    """Save one punch, then recalculate that employee's day."""
    if employee is None:
        employee = match_employee(card_no, device_user_id)
    if employee and PunchLog.objects.filter(employee=employee, punch_time=punch_time).exists():
        return None, False
    log = PunchLog.objects.create(
        employee=employee,
        device=device,
        punch_time=punch_time,
        card_no=str(card_no or ""),
        device_user_id=str(device_user_id or ""),
        source=source,
        raw_status=raw_status,
        is_matched=employee is not None,
        note=note,
    )
    if employee:
        rebuild_day(employee, punch_time.date())
    return log, True


@transaction.atomic
def rebuild_day(employee: User, day: date_cls) -> DailyAttendance | None:
    """Recalculate one employee's day from scratch."""
    shift = employee.effective_shift
    if shift is None:
        return None

    record, _ = DailyAttendance.objects.get_or_create(
        employee=employee, date=day, defaults={"shift": shift}
    )
    if record.is_manual_override:
        return record

    home = HomeOfficeEntry.objects.filter(
        employee=employee, date=day, status=HomeOfficeEntry.Status.APPROVED
    ).first()

    segments = None
    if home:
        mode = DailyAttendance.Mode.HOME
        check_in, check_out = home.check_in, home.check_out
        punch_count = int(bool(check_in)) + int(bool(check_out))
        Outing.objects.filter(employee=employee, date=day).delete()
        paid_out = unpaid_out = trip_count = 0
        inside = None
    else:
        mode = DailyAttendance.Mode.OFFICE
        punches = list(
            PunchLog.objects.filter(employee=employee, punch_time__date=day)
            .order_by("punch_time")
        )
        punch_count = len(punches)
        segments = build_segments([p.punch_time for p in punches], shift)
        check_in, check_out = segments.check_in, segments.check_out
        _label_punches(punches, segments)
        paid_out, unpaid_out, trip_count = _sync_outings(employee, day, record, segments, punches)
        inside = segments.inside_minutes if punches else None

    is_holiday = Holiday.objects.filter(date=day).exists()
    is_on_leave = LeaveRequest.objects.filter(
        employee=employee, status=LeaveRequest.Status.APPROVED,
        start_date__lte=day, end_date__gte=day,
    ).exists()

    ev = evaluate_day(
        shift, day, check_in, check_out,
        mode=mode, is_holiday=is_holiday, is_on_leave=is_on_leave, punch_count=punch_count,
        inside_minutes=inside,
        outside_paid_minutes=paid_out,
        outside_unpaid_minutes=unpaid_out,
        trip_count=trip_count,
    )

    record.shift = shift
    record.mode = (
        DailyAttendance.Mode.HOME if home
        else DailyAttendance.Mode.LEAVE if ev.status == DailyAttendance.Status.LEAVE
        else DailyAttendance.Mode.OFF if ev.status in (
            DailyAttendance.Status.HOLIDAY, DailyAttendance.Status.WEEKEND)
        else DailyAttendance.Mode.OFFICE
    )
    record.check_in = ev.check_in
    record.check_out = ev.check_out
    record.required_out = ev.required_out
    record.worked_minutes = ev.worked_minutes
    record.inside_minutes = ev.inside_minutes
    record.outside_minutes = ev.outside_minutes
    record.outside_paid_minutes = ev.outside_paid_minutes
    record.outside_unpaid_minutes = ev.outside_unpaid_minutes
    record.trip_count = ev.trip_count
    record.late_minutes = ev.late_minutes
    record.early_out_minutes = ev.early_out_minutes
    record.overtime_minutes = ev.overtime_minutes
    record.shortfall_minutes = ev.shortfall_minutes
    record.status = ev.status
    record.is_late = ev.is_late
    record.is_early_out = ev.is_early_out
    record.punch_count = punch_count
    record.remarks = ev.remark_text
    record.save()
    Outing.objects.filter(employee=employee, date=day).update(day=record)
    return record


def _label_punches(punches, segments) -> None:
    """Mark each punch of the day as IN or OUT, and flag duplicate taps."""
    ignored = set(segments.ignored)
    order = {t: i for i, t in enumerate(segments.punches)}
    for punch in punches:
        if punch.punch_time in ignored:
            direction, sequence, is_ignored = PunchLog.Direction.UNKNOWN, 0, True
        else:
            index = order.get(punch.punch_time, -1)
            direction = PunchLog.Direction.IN if index % 2 == 0 else PunchLog.Direction.OUT
            sequence, is_ignored = index + 1, False
        if (punch.direction, punch.sequence, punch.is_ignored) != (direction, sequence, is_ignored):
            punch.direction = direction
            punch.sequence = sequence
            punch.is_ignored = is_ignored
            punch.save(update_fields=["direction", "sequence", "is_ignored"])


def _sync_outings(employee, day, record, segments, punches):
    """Create or refresh an Outing for every trip out of the office.

    Matching is done on the time the employee left, so any purpose or note
    they already wrote survives a recalculation.
    """
    by_time = {p.punch_time: p for p in punches}
    seen = []
    paid = unpaid = 0

    for left_at, returned_at in segments.trips:
        outing, _ = Outing.objects.get_or_create(
            employee=employee, left_at=left_at,
            defaults={"date": day, "day": record},
        )
        outing.date = day
        outing.day = record
        outing.returned_at = returned_at
        outing.out_punch = by_time.get(left_at)
        outing.in_punch = by_time.get(returned_at)
        outing.save()
        seen.append(outing.pk)
        if outing.counts_as_work:
            paid += outing.minutes
        else:
            unpaid += outing.minutes

    # A trip that no longer exists (a punch was deleted or corrected) goes away.
    Outing.objects.filter(employee=employee, date=day).exclude(pk__in=seen).delete()
    return paid, unpaid, len(seen)


def recalc_for_outing(outing) -> None:
    """Called after an employee labels a trip - the day's totals change."""
    rebuild_day(outing.employee, outing.date)


def rebuild_range(day_from: date_cls, day_to: date_cls, employees=None) -> int:
    employees = employees if employees is not None else User.objects.active_staff()
    count = 0
    day = day_from
    while day <= day_to:
        for emp in employees:
            if emp.joining_date and day < emp.joining_date:
                continue
            rebuild_day(emp, day)
            count += 1
        day += timedelta(days=1)
    return count


def mark_absentees(day: date_cls) -> int:
    """Mark employees with no record for the day as absent / weekend / holiday."""
    created = 0
    for emp in User.objects.active_staff():
        if emp.joining_date and day < emp.joining_date:
            continue
        if not DailyAttendance.objects.filter(employee=emp, date=day).exists():
            rebuild_day(emp, day)
            created += 1
    return created


def day_summary(day: date_cls) -> dict:
    qs = DailyAttendance.objects.filter(date=day)
    S = DailyAttendance.Status
    total = User.objects.active_staff().count()
    present = qs.filter(status__in=[S.PRESENT, S.LATE, S.EARLY_OUT, S.LATE_EARLY, S.HALF_DAY, S.MISSING_OUT]).count()
    return {
        "date": day,
        "total": total,
        "present": present,
        "on_time": qs.filter(status=S.PRESENT).count(),
        "late": qs.filter(is_late=True).count(),
        "early_out": qs.filter(is_early_out=True).count(),
        "absent": qs.filter(status=S.ABSENT).count(),
        "leave": qs.filter(status=S.LEAVE).count(),
        "home_office": qs.filter(mode=DailyAttendance.Mode.HOME).count(),
        "still_in": qs.filter(check_in__isnull=False, check_out__isnull=True).count(),
        "not_punched": max(0, total - qs.exclude(status__in=[S.ABSENT, S.WEEKEND, S.HOLIDAY, S.LEAVE]).count()),
    }


def month_summary(employee: User, year: int, month: int) -> dict:
    from calendar import monthrange

    last = monthrange(year, month)[1]
    qs = DailyAttendance.objects.filter(
        employee=employee, date__range=(date_cls(year, month, 1), date_cls(year, month, last))
    )
    S = DailyAttendance.Status
    agg = {
        "days": qs.count(),
        "on_time": qs.filter(status=S.PRESENT).count(),
        "late": qs.filter(is_late=True).count(),
        "early_out": qs.filter(is_early_out=True).count(),
        "absent": qs.filter(status=S.ABSENT).count(),
        "leave": qs.filter(status=S.LEAVE).count(),
        "home_office": qs.filter(mode=DailyAttendance.Mode.HOME).count(),
        "half_day": qs.filter(status=S.HALF_DAY).count(),
        "missing_out": qs.filter(status=S.MISSING_OUT).count(),
        "worked_minutes": sum(qs.values_list("worked_minutes", flat=True)),
        "overtime_minutes": sum(qs.values_list("overtime_minutes", flat=True)),
        "shortfall_minutes": sum(qs.filter(status__in=list(S)).values_list("shortfall_minutes", flat=True)),
        "late_minutes": sum(qs.values_list("late_minutes", flat=True)),
    }
    agg["worked_hours"] = round(agg["worked_minutes"] / 60, 1)
    agg["overtime_hours"] = round(agg["overtime_minutes"] / 60, 1)
    agg["present"] = agg["on_time"] + agg["late"] + agg["early_out"] + agg["half_day"]
    return agg
