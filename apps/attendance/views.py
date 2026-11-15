from calendar import monthrange
from datetime import date as date_cls, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.utils import now as app_now, paginate, today as app_today

from apps.accounts.models import Department, User
from apps.accounts.permissions import manager_required
from apps.leaves.models import LeaveRequest
from apps.tasks.forms import DailyTaskForm
from apps.tasks.models import DailyTask

from .forms import (AttendanceOverrideForm, HolidayForm, HomeOfficeOutForm,
                    HomeOfficeReviewForm, HomeOfficeStartForm, ManualPunchForm,
                    CorrectionDecisionForm, CorrectionRequestForm,
                    OfficeLocationForm, OutingAdminForm, OutingForm,
                    PunchPolicyForm, SelfPunchForm)
from .models import (AttendanceCorrection, DailyAttendance, Holiday, HomeOfficeEntry,
                     OfficeLocation, Outing, PunchLog, PunchPolicy)
from .rules import required_out_time
from .services import (SelfPunchError, apply_correction, attach_punch_locations,
                       day_summary, days_needing_attention, mark_absentees,
                       month_summary, punch_state, rebuild_day, record_punch,
                       reject_correction, self_punch)


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
        "out_now": Outing.objects.filter(date=day, returned_at__isnull=True)
                         .select_related("employee"),
        "todays_outings": Outing.objects.filter(date=day)
                                .select_related("employee").order_by("left_at")[:10],
        "unexplained_trips": Outing.objects.filter(
            date=day, purpose=Outing.Purpose.UNSPECIFIED).count(),
        "unmatched_punches": PunchLog.objects.filter(is_matched=False).count(),
        "former_with_cards": User.objects.filter(is_active=False)
                                 .exclude(rfid_card_no__isnull=True)
                                 .exclude(rfid_card_no="").count(),
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

    # Totals come from the database over the whole range; only the rows shown
    # on screen are actually loaded.
    totals = {
        "rows": qs.count(),
        "late": qs.filter(is_late=True).count(),
        "early": qs.filter(is_early_out=True).count(),
        "absent": qs.filter(status=DailyAttendance.Status.ABSENT).count(),
    }
    page = paginate(request, qs, per_page=50)
    # Where each person punched from, for the rows on screen only.
    records = attach_punch_locations(page.object_list)

    return render(request, "attendance/attendance_sheet.html", {
        "page": page,
        "records": records,
        "day_from": day_from, "day_to": day_to,
        "status": status, "dept": dept, "emp_id": emp_id,
        "statuses": DailyAttendance.Status.choices,
        "departments": Department.objects.all(),
        "employees": User.objects.active_staff(),
        "totals": totals,
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
        from apps.accounts.activity import ActivityLog, log as log_activity
        log_activity(request.user, ActivityLog.Action.ATTENDANCE_EDITED, target=record.employee,
                     subject=f"{record.date:%d %b %Y}",
                     detail=f"in {obj.check_in:%I:%M %p} out {obj.check_out:%I:%M %p}"
                            if obj.check_in and obj.check_out else obj.status)
        messages.success(request, "Attendance record updated.")
        return redirect("attendance:sheet")
    return render(request, "attendance/attendance_edit.html", {"form": form, "record": record})


@manager_required
def punch_log_list(request):
    day = _parse_date(request.GET.get("date"))
    show = request.GET.get("show", "all")
    logs = (PunchLog.objects.filter(punch_time__date=day)
            .select_related("employee", "device", "office"))
    source = request.GET.get("source", "")
    if show == "unmatched":
        logs = logs.filter(is_matched=False)
    if source:
        logs = logs.filter(source=source)
    elif request.GET.get("away") == "1":
        logs = logs.filter(location_status=PunchLog.LocationStatus.OUTSIDE)
    form = ManualPunchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        log, created = record_punch(
            employee=form.cleaned_data["employee"],
            punch_time=form.punch_datetime,
            source=PunchLog.Source.MANUAL,
            note=form.cleaned_data["note"] or f"Manual entry by {request.user.display_name}",
        )
        if created:
            from apps.accounts.activity import ActivityLog, log as log_activity
            log_activity(request.user, ActivityLog.Action.PUNCH_ADDED,
                         target=form.cleaned_data["employee"],
                         subject=f"{form.punch_datetime:%d %b %Y %I:%M %p}",
                         detail=form.cleaned_data["note"])
        messages.success(request, "Punch added." if created else "A punch already exists at that time.")
        return redirect(f"{request.path}?date={form.cleaned_data['punch_date']}")
    page = paginate(request, logs.order_by("punch_time"), per_page=50)
    return render(request, "attendance/punch_logs.html", {
        "page": page, "logs": page.object_list, "day": day, "form": form, "show": show,
        "unmatched_total": PunchLog.objects.filter(is_matched=False).count(),
        "source": source,
        "sources": PunchLog.Source.choices,
        "self_today": logs.filter(source=PunchLog.Source.SELF).count(),
        "away_today": logs.filter(location_status=PunchLog.LocationStatus.OUTSIDE).count(),
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
    page = paginate(request, entries, per_page=30)
    return render(request, "attendance/home_office_review.html", {
        "page": page, "entries": page.object_list, "status": status,
        "form": HomeOfficeReviewForm(),
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
    todays_outings = Outing.objects.filter(employee=me, date=today).order_by("left_at")
    return render(request, "dashboard/employee_portal.html", {
        "punch_state": punch_state(me, today),
        "todays_outings": todays_outings,
        "unlabelled_trips": Outing.objects.filter(
            employee=me, purpose=Outing.Purpose.UNSPECIFIED).count(),
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

        # The same two buttons as the office punch page, but the time and place
        # land on the home office entry instead of the punch log.
        if kind in ("home_in", "home_out"):
            lat = request.POST.get("latitude") or None
            lng = request.POST.get("longitude") or None
            acc = request.POST.get("accuracy_m") or None
            stamp = app_now().replace(microsecond=0)
            if kind == "home_in":
                entry = HomeOfficeEntry.objects.filter(employee=me, date=today).first()
                if entry and entry.check_in:
                    messages.info(request, "You already started your home office day.")
                else:
                    entry = entry or HomeOfficeEntry(employee=me, date=today)
                    entry.reason = entry.reason or request.POST.get("reason") or "Working from home"
                    entry.check_in = stamp
                    entry.in_latitude, entry.in_longitude, entry.in_accuracy_m = lat, lng, acc
                    entry.is_self_punched = True
                    entry.status = HomeOfficeEntry.Status.APPROVED
                    entry.save()
                    messages.success(request, f"Home office started at {stamp:%I:%M %p}.")
            else:
                entry = HomeOfficeEntry.objects.filter(
                    employee=me, check_out__isnull=True).order_by("-date").first()
                if not entry:
                    messages.error(request, "No open home office day to close.")
                else:
                    entry.check_out = stamp
                    entry.out_latitude, entry.out_longitude, entry.out_accuracy_m = lat, lng, acc
                    entry.work_summary = request.POST.get("work_summary") or entry.work_summary
                    entry.save()
                    messages.success(request, f"Home office finished at {stamp:%I:%M %p}.")
            return redirect("attendance:home_office")

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


# ================================================================ TRIPS OUT
@login_required
def my_outings(request):
    """Trips out of the office - the employee says where they went and why."""
    me = request.user
    today = app_today()
    day_from = _parse_date(request.GET.get("from"), today - timedelta(days=13))
    day_to = _parse_date(request.GET.get("to"), today)

    outings = (Outing.objects.filter(employee=me, date__range=(day_from, day_to))
               .select_related("day").order_by("-date", "left_at"))
    totals = outings.aggregate(count=Count("id"), minutes=Sum("minutes"))
    pending_count = outings.filter(purpose=Outing.Purpose.UNSPECIFIED).count()

    if request.method == "POST":
        outing = get_object_or_404(Outing, pk=request.POST.get("outing_id"), employee=me)
        form = OutingForm(request.POST, instance=outing)
        if form.is_valid():
            form.save()
            rebuild_day(me, outing.date)
            messages.success(request, f"Trip at {outing.left_at:%I:%M %p} saved.")
        else:
            messages.error(request, "Please choose a purpose before saving.")
        return redirect(f"{request.path}?from={day_from}&to={day_to}")

    page = paginate(request, outings, per_page=20)

    grouped = {}
    for o in page.object_list:
        grouped.setdefault(o.date, []).append(o)
    rows = [{"date": d, "outings": items, "total": sum(o.minutes for o in items)}
            for d, items in grouped.items()]

    return render(request, "attendance/my_outings.html", {
        "page": page,
        "rows": rows,
        "day_from": day_from, "day_to": day_to,
        "pending": pending_count,
        "total_minutes": totals["minutes"] or 0,
        "trip_count": totals["count"] or 0,
    })


@manager_required
def outing_edit(request, pk):
    """An admin can correct a trip and decide whether it counts as work."""
    outing = get_object_or_404(Outing.objects.select_related("employee"), pk=pk)
    form = OutingAdminForm(request.POST or None, instance=outing)
    if request.method == "POST" and form.is_valid():
        form.save()
        rebuild_day(outing.employee, outing.date)
        messages.success(request, f"{outing.employee.display_name}'s trip updated.")
        return redirect(request.POST.get("next") or "reports:outings")
    return render(request, "attendance/outing_edit.html", {"form": form, "outing": outing})


# ================================================================ SELF PUNCH
def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@login_required
def self_punch_view(request):
    """Punch in or out from a phone or laptop, with the location attached.

    Used when the card reader is down, and by anyone whose work keeps them away
    from the office. The time is taken from the server; the browser only
    supplies where the person was standing.
    """
    me = request.user
    state = punch_state(me)
    form = SelfPunchForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            log, record, direction = self_punch(
                me,
                latitude=data.get("latitude"),
                longitude=data.get("longitude"),
                accuracy_m=data.get("accuracy_m"),
                ip_address=_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                note=data.get("note") or "",
            )
        except SelfPunchError as exc:
            messages.error(request, str(exc))
        else:
            word = "in" if direction == PunchLog.Direction.IN else "out"
            where = ""
            if log.location_status == PunchLog.LocationStatus.INSIDE:
                where = f" at {log.office.name}"
            elif log.location_status == PunchLog.LocationStatus.OUTSIDE:
                where = f" - {log.distance_display} from {log.office.name}"
            messages.success(request, f"Punched {word} at {log.punch_time:%I:%M %p}{where}.")
            if log.location_status == PunchLog.LocationStatus.MISSING:
                messages.warning(request, "No location was attached to that punch.")
        return redirect("attendance:self_punch")

    return render(request, "attendance/self_punch.html", {
        "form": form,
        "state": state,
        "offices": OfficeLocation.objects.filter(is_active=True),
        "today_record": state["record"],
    })


@manager_required
def punch_settings(request):
    """Where the office is, and the rules for punching from a browser."""
    policy = PunchPolicy.get_solo()
    policy_form = PunchPolicyForm(
        request.POST if request.POST.get("form") == "policy" else None, instance=policy)
    office_form = OfficeLocationForm(
        request.POST if request.POST.get("form") == "office" else None)

    if request.method == "POST":
        if request.POST.get("form") == "policy" and policy_form.is_valid():
            policy_form.save()
            messages.success(request, "Punch policy saved.")
            return redirect("attendance:punch_settings")
        if request.POST.get("form") == "office" and office_form.is_valid():
            office = office_form.save()
            messages.success(request, f"{office.name} added.")
            return redirect("attendance:punch_settings")

    return render(request, "settings/punch_settings.html", {
        "policy_form": policy_form,
        "office_form": office_form,
        "offices": OfficeLocation.objects.all(),
        "recent_self_punches": PunchLog.objects.filter(source=PunchLog.Source.SELF)
                                       .select_related("employee", "office")[:10],
    })


@manager_required
def office_delete(request, pk):
    office = get_object_or_404(OfficeLocation, pk=pk)
    office.is_active = not office.is_active
    office.save(update_fields=["is_active"])
    messages.info(request, f"{office.name} is now {'active' if office.is_active else 'off'}.")
    return redirect("attendance:punch_settings")


# ================================================================ CORRECTIONS
@login_required
def my_corrections(request):
    """Ask for a day to be fixed, and see what happened to earlier requests."""
    me = request.user
    form = CorrectionRequestForm(request.POST or None, employee=me)

    if request.method == "POST" and form.is_valid():
        correction = form.save(commit=False)
        correction.employee = me
        correction.save()
        messages.success(
            request,
            f"Request sent for {correction.date:%d %b}. An admin will review it.",
        )
        return redirect("attendance:my_corrections")

    mine = AttendanceCorrection.objects.filter(employee=me).select_related("reviewed_by")
    page = paginate(request, mine, per_page=20)

    return render(request, "attendance/my_corrections.html", {
        "form": form,
        "page": page,
        "corrections": page.object_list,
        "needs_attention": days_needing_attention(me),
        "pending": mine.filter(status=AttendanceCorrection.Status.PENDING).count(),
    })


@login_required
def cancel_correction(request, pk):
    correction = get_object_or_404(AttendanceCorrection, pk=pk, employee=request.user)
    if correction.is_open:
        correction.status = AttendanceCorrection.Status.CANCELLED
        correction.save()
        messages.info(request, "Request cancelled.")
    return redirect("attendance:my_corrections")


@manager_required
def correction_review(request):
    status = request.GET.get("status", "PENDING")
    qs = AttendanceCorrection.objects.select_related("employee", "reviewed_by")
    if status:
        qs = qs.filter(status=status)
    page = paginate(request, qs, per_page=25)

    rows = []
    for correction in page.object_list:
        rows.append({
            "correction": correction,
            "record": DailyAttendance.objects.filter(
                employee=correction.employee, date=correction.date).first(),
        })

    return render(request, "attendance/correction_review.html", {
        "page": page, "rows": rows, "status": status,
        "counts": {s: AttendanceCorrection.objects.filter(status=s).count()
                   for s, _ in AttendanceCorrection.Status.choices},
    })


@manager_required
@require_POST
def correction_decide(request, pk, decision):
    correction = get_object_or_404(AttendanceCorrection, pk=pk)
    if not correction.is_open:
        messages.info(request, "That request has already been decided.")
        return redirect("attendance:correction_review")

    note = request.POST.get("review_note", "")
    if decision == "approve":
        record = apply_correction(correction, by=request.user, note=note)
        messages.success(
            request,
            f"{correction.employee.display_name}'s {correction.date:%d %b} corrected — "
            f"now {record.get_status_display().lower()}, {record.worked_display} worked.",
        )
    else:
        reject_correction(correction, by=request.user, note=note)
        messages.warning(request, "Request rejected. The day is unchanged.")
    return redirect("attendance:correction_review")
