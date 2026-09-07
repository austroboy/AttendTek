"""Leave balances.

A quota is per year, so usage has to be counted per year too. Summing every
approved request ever made means an employee who took ten days in 2026 starts
2027 with nothing left - a quiet, compounding error that nobody notices until
somebody is refused leave they are entitled to.
"""
from __future__ import annotations

from datetime import date as date_cls

from .models import LeaveRequest, LeaveType


def year_bounds(year: int) -> tuple[date_cls, date_cls]:
    return date_cls(year, 1, 1), date_cls(year, 12, 31)


def days_used(employee, leave_type, year: int) -> float:
    """Approved days of one leave type inside one calendar year.

    A request that straddles new year is split, so only the days that fall in
    the year being asked about are counted.
    """
    start, end = year_bounds(year)
    total = 0.0
    approved = LeaveRequest.objects.filter(
        employee=employee, leave_type=leave_type,
        status=LeaveRequest.Status.APPROVED,
        start_date__lte=end, end_date__gte=start,
    )
    for request in approved:
        overlap_start = max(request.start_date, start)
        overlap_end = min(request.end_date, end)
        days = (overlap_end - overlap_start).days + 1
        if request.is_half_day and days == 1:
            days = 0.5
        total += days
    return total


def balance_for(employee, year: int) -> list[dict]:
    """One row per leave type: quota, used and what is left this year."""
    rows = []
    for leave_type in LeaveType.objects.all():
        used = days_used(employee, leave_type, year)
        left = leave_type.annual_quota - used
        rows.append({
            "type": leave_type,
            "quota": leave_type.annual_quota,
            "used": used,
            "left": max(0, left),
            "over": max(0, -left),
            "percent": min(100, round(used / leave_type.annual_quota * 100)) if leave_type.annual_quota else 0,
            "level": "bad" if left < 0 else "warn" if left <= 2 else "ok",
        })
    return rows


def check_request(leave_request) -> dict:
    """What approving this request would do to the employee's balance.

    Shown to the admin before they decide, because the decision is much easier
    to make with the number in front of them than without it.
    """
    year = leave_request.start_date.year
    used = days_used(leave_request.employee, leave_request.leave_type, year)
    quota = leave_request.leave_type.annual_quota
    asked = leave_request.total_days
    after = used + asked
    return {
        "year": year,
        "quota": quota,
        "used": used,
        "asked": asked,
        "after": after,
        "left_after": quota - after,
        "exceeds": after > quota,
        "over_by": max(0, after - quota),
    }
