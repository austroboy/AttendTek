from calendar import monthrange
from datetime import date as date_cls, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.utils import now as app_now, today as app_today

from apps.accounts.models import Department, User
from apps.accounts.permissions import manager_required
from apps.leaves.models import LeaveRequest
from apps.tasks.forms import DailyTaskForm
from apps.tasks.models import DailyTask

from .forms import (AttendanceOverrideForm, HolidayForm, HomeOfficeOutForm,
                    HomeOfficeReviewForm, HomeOfficeStartForm, ManualPunchForm)
from .models import DailyAttendance, Holiday, HomeOfficeEntry, PunchLog
from .rules import required_out_time
from .services import day_summary, mark_absentees, month_summary, rebuild_day, record_punch


def _parse_date(value, fallback=None):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return fallback or app_today()


# ================================================================ ADMIN SIDE
@manager_required
def dashboard(request):
    day = _parse_date(request.GET.get("date"))
    summary = day_summary(day)
    records = (DailyAttendance.objects.filter(date=day)
               .select_related("employee", "employee__department", "shift")
               .order_by("check_in"))

    # last 7 days trend
    trend = []
    for i in range(6, -1, -1):
        d = day - timedelta(days=i)
        s = DailyAttendance.objects.filter(date=d)
        trend.append({
            "date": d,
            "on_time": s.filter(status=DailyAttendance.Status.PRESENT).count(),
            "late": s.filter(is_late=True).count(),
            "absent": s.filter(status=DailyAttendance.Status.ABSENT).count(),
        })

    return render(request, "dashboard/admin_dashboard.html", {
        "day": day,
        "summary": summary,
        "records": records,
        "trend": trend,
        "max_trend": max([t["on_time"] + t["late"] + t["absent"] for t in trend] + [1]),
        "late_list": records.filter(is_late=True)[:8],
        "still_in": records.filter(check_in__isnull=False, check_out__isnull=True),
        "pending_leave_list": LeaveRequest.objects.filter(status="PENDING").select_related("employee")[:5],
        "pending_home_list": HomeOfficeEntry.objects.filter(status="PENDING").select_related("employee")[:5],
        "unmatched_punches": PunchLog.objects.filter(is_matched=False).count(),
        "no_card": User.objects.filter(is_active=True).filter(
            Q(rfid_card_no__isnull=True) | Q(rfid_card_no="")).count(),
        "today_tasks": DailyTask.objects.filter(date=day).select_related("employee")[:6],
    })


@manager_required
def attendance_sheet(request):
    """Attendance for every employee, with filters."""
    day_from = _parse_date(request.GET.get("from"), app_today() - timedelta(days=6))
    day_to = _parse_date(request.GET.get("to"))
    status = request.GET.get("status", "")
    dept = request.GET.get("dept", "")
    emp_id = request.GET.get("employee", "")

    qs = (DailyAttendance.objects.filter(date__range=(day_from, day_to))
          .select_related("employee", "employee__department", "shift"))
    if status == "problem":
        qs = qs.filter(Q(is_late=True) | Q(is_early_out=True)
                       | Q(status__in=[DailyAttendance.Status.ABSENT, DailyAttendance.Status.MISSING_OUT]))
    elif status:
        qs = qs.filter(status=status)
    if dept:
        qs = qs.filter(employee__department_id=dept)
    if emp_id:
        qs = qs.filter(employee_id=emp_id)

    return render(request, "attendance/attendance_sheet.html", {
        "records": qs[:600],
        "day_from": day_from, "day_to": day_to,
        "status": status, "dept": dept, "emp_id": emp_id,
        "statuses": DailyAttendance.Status.choices,
        "departments": Department.objects.all(),
        "employees": User.objects.active_staff(),
        "totals": {
            "rows": qs.count(),
            "late": qs.filter(is_late=True).count(),
            "early": qs.filter(is_early_out=True).count(),
            "absent": qs.filter(status=DailyAttendance.Status.ABSENT).count(),
        },
    })


@manager_required
def attendance_edit(request, pk):
    record = get_object_or_404(DailyAttendance.objects.select_related("employee", "shift"), pk=pk)
    form = AttendanceOverrideForm(request.POST or None, instance=record)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        in_t, out_t = form.cleaned_data.get("in_time"), form.cleaned_data.get("out_time")
        obj.check_in = datetime.combine(record.date, in_t) if in_t else None
        obj.check_out = datetime.combine(record.date, out_t) if out_t else None
        if obj.check_in and record.shift:
            obj.required_out = required_out_time(record.shift, record.date, obj.check_in)
            if obj.check_out:
                obj.worked_minutes = int((obj.check_out - obj.check_in).total_seconds() // 60)
        obj.save()
        if not obj.is_manual_override:
            rebuild_day(record.employee, record.date)
        messages.success(request, "Attendance record updated.")
        return redirect("attendance:sheet")
    return render(request, "attendance/attendance_edit.html", {"form": form, "record": record})


@manager_required
def punch_log_list(request):
    day = _parse_date(request.GET.get("date"))
    show = request.GET.get("show", "all")
    logs = PunchLog.objects.filter(punch_time__date=day).select_related("employee", "device")
    if show == "unmatched":
        logs = logs.filter(is_matched=False)
    form = ManualPunchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        log, created = record_punch(
            employee=form.cleaned_data["employee"],
            punch_time=form.punch_datetime,
            source=PunchLog.Source.MANUAL,
            note=form.cleaned_data["note"] or f"Manual entry by {request.user.display_name}",
        )
        messages.success(request, "Punch added." if created else "A punch already exists at that time.")
        return redirect(f"{request.path}?date={form.cleaned_data['punch_date']}")
    return render(request, "attendance/punch_logs.html", {
        "logs": logs.order_by("punch_time"), "day": day, "form": form, "show": show,
        "unmatched_total": PunchLog.objects.filter(is_matched=False).count(),
    })


@manager_required
def punch_log_link(request, pk):
    """Link an unmatched punch to an employee."""
    log = get_object_or_404(PunchLog, pk=pk)
    emp = get_object_or_404(User, pk=request.POST.get("employee"))
    log.employee = emp
    log.is_matched = True
    log.save()
    if not emp.rfid_card_no and log.card_no:
        emp.rfid_card_no = log.card_no
        emp.save(update_fields=["rfid_card_no"])
        messages.info(request, f"{log.card_no} Card {emp.display_name}  saved to this employee.")
    rebuild_day(emp, log.punch_time.date())
    messages.success(request, "Punch linked.")
    return redirect("attendance:punch_logs")


@manager_required
def recalculate(request):
    day_from = _parse_date(request.POST.get("from"), app_today())
    day_to = _parse_date(request.POST.get("to"), app_today())
    from .services import rebuild_range
    rebuild_range(day_from, day_to)
    messages.success(request, f"{day_from:%d %b} - {day_to:%d %b} recalculated.")
    return redirect(request.POST.get("next") or "attendance:dashboard")


@manager_required
def home_office_review(request):
    status = request.GET.get("status", "")
    entries = HomeOfficeEntry.objects.select_related("employee")
    if status:
        entries = entries.filter(status=status)
    return render(request, "attendance/home_office_review.html", {
        "entries": entries, "status": status, "form": HomeOfficeReviewForm(),
    })


@manager_required
def home_office_decide(request, pk, decision):
    entry = get_object_or_404(HomeOfficeEntry, pk=pk)
    entry.status = (HomeOfficeEntry.Status.APPROVED if decision == "approve"
                    else HomeOfficeEntry.Status.REJECTED)
    entry.reviewed_by = request.user
    entry.review_note = request.POST.get("review_note", "")
    entry.reviewed_at = timezone.now()
    entry.save()
    messages.success(request, f"{entry.employee.display_name} 's home office request was {entry.get_status_display().lower()}.")
    return redirect("attendance:home_office_review")


@manager_required
def holiday_list(request):
    form = HolidayForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        h = form.save()
        from .services import rebuild_range
        rebuild_range(h.date, h.date)
        messages.success(request, "Holiday added.")
        return redirect("attendance:holidays")
    return render(request, "settings/holiday_list.html",
                  {"form": form, "holidays": Holiday.objects.all()})


# ================================================================ EMPLOYEE SIDE
@login_required
def my_portal(request):
    """The employee's own portal - today's status, tasks, home office and leave."""
    today = app_today()
    me = request.user
    record = DailyAttendance.objects.filter(employee=me, date=today).first()
    if record is None:
        record = rebuild_day(me, today)

    open_home = HomeOfficeEntry.objects.filter(
        employee=me, date=today, check_out__isnull=True).first()

    task_form = DailyTaskForm(request.POST or None)
    if request.method == "POST" and request.POST.get("form") == "task" and task_form.is_valid():
        task = task_form.save(commit=False)
        task.employee = me
        task.save()
        messages.success(request, "Task added.")
        return redirect("attendance:my_portal")

    shift = me.effective_shift
    return render(request, "dashboard/employee_portal.html", {
        "today": today,
        "record": record,
        "shift": shift,
        "open_home": open_home,
        "task_form": task_form,
        "today_tasks": DailyTask.objects.filter(employee=me, date=today),
        "week": DailyAttendance.objects.filter(
            employee=me, date__range=(today - timedelta(days=6), today)).order_by("date"),
        "summary": month_summary(me, today.year, today.month),
        "my_leaves": me.leave_requests.all()[:4],
        "my_home_office": me.home_office_entries.all()[:4],
    })


@login_required
def my_attendance(request):
    """The employee's own monthly attendance calendar and list."""
    today = app_today()
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))
    first = date_cls(year, month, 1)
    last = date_cls(year, month, monthrange(year, month)[1])

    records = {r.date: r for r in DailyAttendance.objects.filter(
        employee=request.user, date__range=(first, last)).select_related("shift")}

    # calendar grid (Monday first)
    cells = []
    lead = first.weekday()
    for _ in range(lead):
        cells.append(None)
    d = first
    while d <= last:
        cells.append({"date": d, "record": records.get(d)})
        d += timedelta(days=1)

    return render(request, "attendance/my_attendance.html", {
        "cells": cells,
        "records": sorted(records.values(), key=lambda r: r.date, reverse=True),
        "year": year, "month": month,
        "month_name": first.strftime("%B %Y"),
        "prev": (first - timedelta(days=1)),
        "next": (last + timedelta(days=1)),
        "summary": month_summary(request.user, year, month),
    })


@login_required
def home_office(request):
    """Pick home office and log in/out times."""
    me = request.user
    today = app_today()
    running = HomeOfficeEntry.objects.filter(employee=me, check_out__isnull=True).order_by("-date").first()

    start_form = HomeOfficeStartForm(employee=me)
    out_form = HomeOfficeOutForm(instance=running) if running else None

    if request.method == "POST":
        kind = request.POST.get("form")
        if kind == "start":
            start_form = HomeOfficeStartForm(request.POST, employee=me)
            if start_form.is_valid():
                start_form.save()
                messages.success(request, "In time recorded. Your day is now marked as home office.")
                return redirect("attendance:home_office")
        elif kind == "out" and running:
            out_form = HomeOfficeOutForm(request.POST, instance=running)
            if out_form.is_valid():
                out_form.save()
                messages.success(request, "Out time recorded.")
                return redirect("attendance:home_office")

    return render(request, "attendance/home_office.html", {
        "start_form": start_form,
        "out_form": out_form,
        "running": running,
        "entries": me.home_office_entries.all()[:20],
        "today": today,
        "can_home_office": me.can_home_office,
    })
