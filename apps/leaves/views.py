from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.attendance.models import HomeOfficeEntry
from apps.utils import paginate, today as app_today

from apps.accounts.permissions import manager_required

from .forms import LeaveRequestForm, LeaveTypeForm
from .models import LeaveRequest, LeaveType
from .services import balance_for, check_request


@login_required
def my_leaves(request):
    me = request.user
    form = LeaveRequestForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        leave = form.save(commit=False)
        leave.employee = me
        leave.save()
        messages.success(request, "Leave request submitted and waiting for approval.")
        return redirect("leaves:my_leaves")

    requests_qs = me.leave_requests.select_related("leave_type", "reviewed_by")
    year = int(request.GET.get("year", app_today().year))
    page = paginate(request, requests_qs, per_page=20)
    return render(request, "leaves/my_leaves.html", {
        "form": form, "page": page, "requests": page.object_list,
        "balance": balance_for(me, year),
        "year": year,
        "this_year": app_today().year,
    })


@login_required
def cancel_leave(request, pk):
    leave = get_object_or_404(LeaveRequest, pk=pk, employee=request.user)
    if leave.status == LeaveRequest.Status.PENDING:
        leave.status = LeaveRequest.Status.CANCELLED
        leave.save()
        messages.info(request, "Leave request cancelled.")
    return redirect("leaves:my_leaves")


@login_required
def team_leaves(request):
    """Everyone can see who is on leave and where each request stands.

    Only admins and HR see the reason and the approve/reject buttons - the
    rest of the team sees the person, the leave type, the dates and the status.
    """
    day = app_today()
    status = request.GET.get("status", "")
    month = request.GET.get("month", "")

    requests_qs = (LeaveRequest.objects
                   .select_related("employee", "employee__department", "leave_type", "reviewed_by")
                   .exclude(status=LeaveRequest.Status.CANCELLED))
    if status:
        requests_qs = requests_qs.filter(status=status)
    if month:
        try:
            year, mon = (int(x) for x in month.split("-"))
            first = date(year, mon, 1)
            last = date(year + (mon == 12), (mon % 12) + 1, 1) - timedelta(days=1)
            requests_qs = requests_qs.filter(start_date__lte=last, end_date__gte=first)
        except (ValueError, TypeError):
            pass

    approved = LeaveRequest.objects.filter(status=LeaveRequest.Status.APPROVED)
    on_leave_today = (approved.filter(start_date__lte=day, end_date__gte=day)
                      .select_related("employee", "leave_type"))
    upcoming = (approved.filter(start_date__gt=day, start_date__lte=day + timedelta(days=14))
                .select_related("employee", "leave_type").order_by("start_date")[:10])
    home_office_today = (HomeOfficeEntry.objects
                         .filter(date=day, status=HomeOfficeEntry.Status.APPROVED)
                         .select_related("employee"))

    page = paginate(request, requests_qs, per_page=25)
    return render(request, "leaves/team_leaves.html", {
        "day": day,
        "page": page,
        "requests": page.object_list,
        "on_leave_today": on_leave_today,
        "upcoming": upcoming,
        "home_office_today": home_office_today,
        "pending_count": LeaveRequest.objects.filter(status=LeaveRequest.Status.PENDING).count(),
        "status": status,
        "month": month,
        "statuses": [c for c in LeaveRequest.Status.choices if c[0] != "CANCELLED"],
        "can_approve": request.user.is_manager,
    })


@manager_required
def leave_review(request):
    status = request.GET.get("status", "PENDING")
    qs = LeaveRequest.objects.select_related("employee", "leave_type", "reviewed_by")
    if status:
        qs = qs.filter(status=status)
    page = paginate(request, qs, per_page=25)
    rows = [{"leave": leave, "balance": check_request(leave)} for leave in page.object_list]
    return render(request, "leaves/leave_review.html", {
        "page": page, "rows": rows, "requests": page.object_list, "status": status,
        "counts": {s: LeaveRequest.objects.filter(status=s).count()
                   for s, _ in LeaveRequest.Status.choices},
    })


@manager_required
def leave_decide(request, pk, decision):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    from apps.accounts.activity import ActivityLog, log as log_activity

    note = request.POST.get("review_note", "")
    log_activity(request.user, ActivityLog.Action.LEAVE_DECIDED, target=leave.employee,
                 subject=f"{leave.leave_type.name} {leave.start_date:%d %b} – {leave.end_date:%d %b}",
                 detail=f"{decision} · {note}")
    if decision == "approve":
        leave.approve(request.user, note)
        messages.success(request, f"{leave.employee.display_name}'s leave was approved.")
    else:
        leave.reject(request.user, note)
        messages.warning(request, f"{leave.employee.display_name}'s leave was rejected.")
    return redirect(request.POST.get("next") or "leaves:review")


@manager_required
def leave_type_list(request):
    form = LeaveTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Leave type added.")
        return redirect("leaves:types")
    return render(request, "leaves/leave_types.html", {"form": form, "types": LeaveType.objects.all()})
