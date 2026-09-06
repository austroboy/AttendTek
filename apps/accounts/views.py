from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.utils import now as app_now, today as app_today

from apps.attendance.models import DailyAttendance
from apps.attendance.services import month_summary
from apps.utils import paginate

from .forms import (CardAssignForm, ChangePasswordForm, DeactivateEmployeeForm,
                    DepartmentForm, DesignationForm, EmployeeForm, LoginForm,
                    ProfileForm, ShiftForm)
from .models import Department, Designation, Shift, User
from .offboarding import deactivate_employee, reactivate_employee
from .permissions import manager_required


def root_redirect(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    if request.user.is_manager:
        return redirect("attendance:dashboard")
    return redirect("attendance:my_portal")


class AppLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


def logout_view(request):
    logout(request)
    messages.info(request, "You have been signed out.")
    return redirect("accounts:login")


# ---------------------------------------------------------------- employees
@manager_required
def employee_list(request):
    q = request.GET.get("q", "").strip()
    dept = request.GET.get("dept", "")
    card = request.GET.get("card", "")
    status = request.GET.get("status", "active")
    employees = User.objects.select_related("department", "designation", "shift")
    if status == "active":
        employees = employees.filter(is_active=True)
    elif status == "former":
        employees = employees.filter(is_active=False)
    if q:
        employees = employees.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q)
            | Q(employee_id__icontains=q) | Q(rfid_card_no__icontains=q)
            | Q(username__icontains=q)
        )
    if dept:
        employees = employees.filter(department_id=dept)
    if card == "missing":
        employees = employees.filter(Q(rfid_card_no__isnull=True) | Q(rfid_card_no=""))
    elif card == "assigned":
        employees = employees.exclude(Q(rfid_card_no__isnull=True) | Q(rfid_card_no=""))
    page = paginate(request, employees.order_by("employee_id"), per_page=25)
    return render(request, "accounts/employee_list.html", {
        "page": page,
        "employees": page.object_list,
        "departments": Department.objects.all(),
        "q": q, "dept": dept, "card": card, "status": status,
        "active_count": User.objects.filter(is_active=True).count(),
        "former_count": User.objects.filter(is_active=False).count(),
        "no_card_count": User.objects.filter(
            is_active=True).filter(Q(rfid_card_no__isnull=True) | Q(rfid_card_no="")).count(),
    })


@manager_required
def employee_create(request):
    form = EmployeeForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        emp = form.save()
        messages.success(request, f"{emp.display_name} has been added.")
        return redirect("accounts:employee_detail", pk=emp.pk)
    return render(request, "accounts/employee_form.html", {"form": form, "title": "Add employee"})


@manager_required
def employee_edit(request, pk):
    emp = get_object_or_404(User, pk=pk)
    form = EmployeeForm(request.POST or None, request.FILES or None, instance=emp)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Employee updated.")
        return redirect("accounts:employee_detail", pk=emp.pk)
    return render(request, "accounts/employee_form.html",
                  {"form": form, "title": f"Edit {emp.display_name}", "employee": emp})


@manager_required
def employee_detail(request, pk):
    emp = get_object_or_404(User.objects.select_related("department", "designation", "shift"), pk=pk)
    today = app_today()
    card_form = CardAssignForm(request.POST or None, instance=emp)
    if request.method == "POST" and card_form.is_valid():
        card_form.save()
        messages.success(request, f"Card ID saved: {emp.rfid_card_no}")
        return redirect("accounts:employee_detail", pk=emp.pk)
    return render(request, "accounts/employee_detail.html", {
        "employee": emp,
        "card_form": card_form,
        "summary": month_summary(emp, today.year, today.month),
        "recent": DailyAttendance.objects.filter(employee=emp).order_by("-date")[:14],
        "recent_tasks": emp.daily_tasks.all()[:8],
        "leaves": emp.leave_requests.all()[:5],
    })


@manager_required
def employee_deactivate(request, pk):
    """Record that someone has left and close their access."""
    emp = get_object_or_404(User, pk=pk)

    if not emp.is_active:
        messages.info(request, f"{emp.display_name} is already deactivated.")
        return redirect("accounts:employee_detail", pk=emp.pk)

    if emp == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("accounts:employee_detail", pk=emp.pk)

    form = DeactivateEmployeeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        result = deactivate_employee(
            emp,
            by=request.user,
            exit_date=form.cleaned_data["exit_date"],
            reason=form.cleaned_data["reason"],
            note=form.cleaned_data["note"],
            cancel_pending=form.cleaned_data["cancel_pending"],
        )
        messages.success(
            request,
            f"{emp.display_name} has been deactivated. "
            f"{result['sessions_ended']} open session(s) ended, "
            f"{result['future_days_removed']} future attendance day(s) cleared.",
        )
        return redirect("accounts:employee_detail", pk=emp.pk)

    return render(request, "accounts/employee_deactivate.html", {
        "form": form,
        "employee": emp,
        "pending_leaves": emp.leave_requests.filter(status="PENDING").count(),
    })


@manager_required
def employee_reactivate(request, pk):
    """Bring someone back - a rejoin, or an undo."""
    emp = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        reactivate_employee(emp, by=request.user)
        messages.success(
            request,
            f"{emp.display_name} is active again. Attendance will be counted from today.",
        )
    return redirect("accounts:employee_detail", pk=emp.pk)


@manager_required
def card_assign_board(request):
    """A single board for assigning card IDs to every employee."""
    if request.method == "POST":
        updated = 0
        for key, value in request.POST.items():
            if not key.startswith("card_"):
                continue
            pk = key.split("_", 1)[1]
            value = value.strip()
            emp = User.objects.filter(pk=pk).first()
            if not emp:
                continue
            new_card = value or None
            if new_card != emp.rfid_card_no:
                if new_card and User.objects.filter(rfid_card_no__iexact=new_card).exclude(pk=emp.pk).exists():
                    messages.error(request, f"{new_card} is already assigned to someone else — {emp.display_name} was skipped.")
                    continue
                emp.rfid_card_no = new_card
                emp.card_issued_on = emp.card_issued_on or app_today()
                emp.save(update_fields=["rfid_card_no", "card_issued_on"])
                updated += 1
        messages.success(request, f"{updated} card IDs updated.")
        return redirect("accounts:card_board")
    page = paginate(
        request,
        User.objects.filter(is_active=True).select_related("department").order_by("employee_id"),
        per_page=40,
    )
    return render(request, "accounts/card_board.html", {
        "page": page, "employees": page.object_list,
    })


# ---------------------------------------------------------------- profile
@login_required
def profile(request):
    """The employee's own page: who they are, and how their month is going."""
    me = request.user
    today = app_today()
    which = request.POST.get("form") if request.method == "POST" else None

    form = ProfileForm(
        request.POST if which == "profile" else None,
        request.FILES if which == "profile" else None,
        instance=me,
    )
    password_form = ChangePasswordForm(me, request.POST if which == "password" else None)

    if which == "profile" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")

    if which == "password" and password_form.is_valid():
        password_form.save()
        # Without this the person is logged out the moment their password changes.
        update_session_auth_hash(request, me)
        messages.success(request, "Password changed. Keep the new one to yourself.")
        return redirect("accounts:profile")

    summary = month_summary(me, today.year, today.month)
    recent = DailyAttendance.objects.filter(employee=me).order_by("-date")[:7]

    tenure = None
    if me.joining_date:
        days = (today - me.joining_date).days
        years, remainder = divmod(days, 365)
        months = remainder // 30
        parts = []
        if years:
            parts.append(f"{years} year{'s' if years > 1 else ''}")
        if months:
            parts.append(f"{months} month{'s' if months > 1 else ''}")
        tenure = " ".join(parts) or f"{days} days"

    return render(request, "accounts/profile.html", {
        "form": form,
        "password_form": password_form,
        "summary": summary,
        "recent": recent,
        "tenure": tenure,
        "month_label": today.strftime("%B %Y"),
        "leave_count": me.leave_requests.filter(status="APPROVED").count(),
        "task_count": me.daily_tasks.count(),
    })


# ---------------------------------------------------------------- settings
@manager_required
def settings_home(request):
    return render(request, "settings/settings_home.html", {
        "shifts": Shift.objects.all(),
        "departments": Department.objects.all(),
        "designations": Designation.objects.all(),
    })


@manager_required
def shift_form(request, pk=None):
    shift = get_object_or_404(Shift, pk=pk) if pk else None
    form = ShiftForm(request.POST or None, instance=shift)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Shift rules saved.")
        return redirect("accounts:settings")
    return render(request, "settings/shift_form.html", {"form": form, "shift": shift})


@manager_required
def department_form(request):
    form = DepartmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Department added.")
        return redirect("accounts:settings")
    return render(request, "settings/simple_form.html", {"form": form, "title": "Add department"})


@manager_required
def designation_form(request):
    form = DesignationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Designation added.")
        return redirect("accounts:settings")
    return render(request, "settings/simple_form.html", {"form": form, "title": "Add designation"})
