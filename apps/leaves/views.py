from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.attendance.models import HomeOfficeEntry
from apps.utils import today as app_today

from apps.accounts.permissions import manager_required

from .forms import LeaveRequestForm, LeaveTypeForm
from .models import LeaveRequest, LeaveType


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
    used = {}
    for lt in LeaveType.objects.all():
        taken = sum(r.total_days for r in requests_qs.filter(leave_type=lt, status="APPROVED"))
        used[lt] = {"taken": taken, "left": max(0, lt.annual_quota - taken), "quota": lt.annual_quota}
    return render(request, "leaves/my_leaves.html", {
        "form": form, "requests": requests_qs[:30], "balance": used,
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

    return render(request, "leaves/team_leaves.html", {
        "day": day,
        "requests": requests_qs[:200],
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
    return render(request, "leaves/leave_review.html", {
        "requests": qs[:200], "status": status,
        "counts": {s: LeaveRequest.objects.filter(status=s).count()
                   for s, _ in LeaveRequest.Status.choices},
    })


@manager_required
def leave_decide(request, pk, decision):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    note = request.POST.get("review_note", "")
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
