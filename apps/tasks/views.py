from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.permissions import manager_required

from .forms import DailyTaskForm
from .models import DailyTask


@login_required
def my_tasks(request):
    me = request.user
    form = DailyTaskForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.employee = me
        task.save()
        messages.success(request, "Task saved.")
        return redirect("tasks:my_tasks")

    tasks = DailyTask.objects.filter(employee=me)[:120]
    grouped = {}
    for t in tasks:
        grouped.setdefault(t.date, []).append(t)
    return render(request, "tasks/my_tasks.html", {
        "form": form,
        "grouped": sorted(grouped.items(), reverse=True),
        "total_hours": sum(float(t.hours_spent) for t in tasks),
    })


@login_required
def task_delete(request, pk):
    task = get_object_or_404(DailyTask, pk=pk, employee=request.user)
    task.delete()
    messages.info(request, "Task deleted.")
    return redirect("tasks:my_tasks")


@manager_required
def task_board(request):
    """Admins review every employee's daily tasks."""
    from apps.attendance.views import _parse_date

    day = _parse_date(request.GET.get("date"))
    emp_id = request.GET.get("employee", "")
    tasks = DailyTask.objects.filter(date=day).select_related("employee", "employee__department")
    if emp_id:
        tasks = tasks.filter(employee_id=emp_id)

    by_employee = {}
    for t in tasks:
        by_employee.setdefault(t.employee, []).append(t)

    submitted = set(t.employee_id for t in tasks)
    missing = [e for e in User.objects.active_staff() if e.id not in submitted]

    return render(request, "tasks/task_board.html", {
        "day": day,
        "by_employee": sorted(by_employee.items(), key=lambda kv: kv[0].employee_id),
        "missing": missing,
        "employees": User.objects.active_staff(),
        "emp_id": emp_id,
        "prev_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1),
    })
