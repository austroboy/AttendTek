"""Rolling up daily task entries into day, week and month figures.

A task log is only useful when it can be read back at the length people
actually think in: what did I do today, how did last week go, where did the
month go. The same helpers serve both the employee's own view and the admin's,
so the two can never quietly disagree with each other.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date as date_cls, timedelta

from django.db.models import Count, Sum

from apps.attendance.models import DailyAttendance

from .models import DailyTask

PERIODS = (("day", "Day"), ("week", "Week"), ("month", "Month"))


def period_bounds(kind: str, anchor: date_cls):
    """Start and end date of the day, week or month containing `anchor`.

    Weeks run Monday to Sunday, which is how the office week reads even when
    the weekend falls on Friday and Saturday.
    """
    if kind == "day":
        return anchor, anchor, anchor.strftime("%A, %d %B %Y")
    if kind == "week":
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=6)
        if start.month == end.month:
            label = f"{start:%d} – {end:%d %B %Y}"
        else:
            label = f"{start:%d %b} – {end:%d %b %Y}"
        return start, end, label
    start = anchor.replace(day=1)
    end = anchor.replace(day=monthrange(anchor.year, anchor.month)[1])
    return start, end, anchor.strftime("%B %Y")


def shift_period(kind: str, anchor: date_cls, step: int) -> date_cls:
    """The same period, `step` places forward or back."""
    if kind == "day":
        return anchor + timedelta(days=step)
    if kind == "week":
        return anchor + timedelta(weeks=step)
    month = anchor.month - 1 + step
    year = anchor.year + month // 12
    month = month % 12 + 1
    return date_cls(year, month, min(anchor.day, monthrange(year, month)[1]))


def summarise(tasks, start: date_cls, end: date_cls) -> dict:
    """Totals, and the same total sliced by day, project and progress."""
    tasks = list(tasks)
    total = sum(t.minutes_spent for t in tasks)

    per_day = {}
    per_project = {}
    per_progress = {}
    for t in tasks:
        per_day[t.date] = per_day.get(t.date, 0) + t.minutes_spent
        key = t.project.strip() or "Unassigned"
        per_project[key] = per_project.get(key, 0) + t.minutes_spent
        per_progress[t.get_progress_display()] = (
            per_progress.get(t.get_progress_display(), 0) + t.minutes_spent
        )

    days = []
    cursor = start
    while cursor <= end:
        minutes = per_day.get(cursor, 0)
        days.append({
            "date": cursor,
            "minutes": minutes,
            "display": DailyTask.format_minutes(minutes),
            "is_logged": minutes > 0,
        })
        cursor += timedelta(days=1)

    logged_days = sum(1 for d in days if d["is_logged"])
    return {
        "tasks": tasks,
        "task_count": len(tasks),
        "total_minutes": total,
        "total_display": DailyTask.format_minutes(total),
        "days": days,
        "logged_days": logged_days,
        "busiest": max(days, key=lambda d: d["minutes"]) if days else None,
        "daily_average": DailyTask.format_minutes(round(total / logged_days)) if logged_days else "—",
        "peak_minutes": max((d["minutes"] for d in days), default=0),
        "projects": sorted(
            ({"name": k, "minutes": v, "display": DailyTask.format_minutes(v),
              "share": round(v / total * 100) if total else 0}
             for k, v in per_project.items()),
            key=lambda r: -r["minutes"],
        ),
        "progress": sorted(
            ({"name": k, "minutes": v, "display": DailyTask.format_minutes(v)}
             for k, v in per_progress.items()),
            key=lambda r: -r["minutes"],
        ),
    }


def attendance_minutes(employee, start: date_cls, end: date_cls) -> int:
    """How long the employee was actually at work over the period."""
    return DailyAttendance.objects.filter(
        employee=employee, date__range=(start, end)
    ).aggregate(total=Sum("worked_minutes"))["total"] or 0


def coverage(logged: int, worked: int) -> dict:
    """How much of the time at work is accounted for by the task log.

    Not a judgement on anybody - meetings, interruptions and admin work rarely
    make it into a task log, so a healthy number is high but never 100.
    """
    percent = round(logged / worked * 100) if worked else 0
    return {
        "logged": logged,
        "worked": worked,
        "logged_display": DailyTask.format_minutes(logged),
        "worked_display": DailyTask.format_minutes(worked),
        "percent": percent,
        "bar": min(percent, 100),
        "gap_display": DailyTask.format_minutes(max(worked - logged, 0)),
        "level": "ok" if percent >= 70 else "warn" if percent >= 40 else "bad",
    }


def employee_rows(employees, start: date_cls, end: date_cls):
    """One row per employee for the admin table."""
    logged = {
        r["employee_id"]: r
        for r in DailyTask.objects.filter(date__range=(start, end), employee__in=employees)
        .values("employee_id")
        .annotate(minutes=Sum("minutes_spent"), tasks=Count("id"),
                  days=Count("date", distinct=True))
    }
    worked = {
        r["employee_id"]: r["minutes"]
        for r in DailyAttendance.objects.filter(date__range=(start, end), employee__in=employees)
        .values("employee_id").annotate(minutes=Sum("worked_minutes"))
    }

    rows = []
    for emp in employees:
        stats = logged.get(emp.id, {})
        minutes = stats.get("minutes") or 0
        rows.append({
            "employee": emp,
            "tasks": stats.get("tasks") or 0,
            "days_logged": stats.get("days") or 0,
            "minutes": minutes,
            "display": DailyTask.format_minutes(minutes),
            "coverage": coverage(minutes, worked.get(emp.id, 0)),
        })
    return sorted(rows, key=lambda r: -r["minutes"])
