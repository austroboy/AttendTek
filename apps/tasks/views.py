from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.permissions import manager_required

from .forms import DailyTaskForm
from .models import DailyTask
from .services import (PERIODS, attendance_minutes, coverage, period_bounds,
                       shift_period, summarise)


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

    # Each day gets its own total, so the employee can see whether what they
    # logged lines up with the hours they were actually at work.
    days = []
    for day, items in sorted(grouped.items(), reverse=True):
        minutes = sum(t.minutes_spent for t in items)
        days.append({"date": day, "tasks": items, "minutes": minutes,
                     "total": DailyTask.format_minutes(minutes)})

    total = sum(t.minutes_spent for t in tasks)
    return render(request, "tasks/my_tasks.html", {
        "form": form,
        "days": days,
        "total_logged": DailyTask.format_minutes(total),
        "task_count": len(tasks),
    })


def _own_task(request, pk):
    """The employee's own task - or any task when a manager is correcting one."""
    task = get_object_or_404(DailyTask.objects.select_related("employee"), pk=pk)
    if task.employee_id != request.user.id and not request.user.is_manager:
        raise PermissionDenied("That task belongs to someone else.")
    return task


@login_required
def task_edit(request, pk):
    """Change a task after logging it - most often to close off something
    that was still in progress when it was first written down."""
    task = _own_task(request, pk)
    form = DailyTaskForm(request.POST or None, instance=task)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f'"{task.title}" updated.')
        return redirect(request.POST.get("next") or "tasks:my_tasks")
    return render(request, "tasks/task_form.html", {
        "form": form, "task": task,
        "next": request.GET.get("next", ""),
    })


@login_required
@require_POST
def task_set_progress(request, pk, progress):
    """One-click way to move a task to done, in progress or blocked."""
    task = _own_task(request, pk)
    valid = dict(DailyTask.Progress.choices)
    if progress not in valid:
        messages.error(request, "Unknown status.")
    else:
        task.progress = progress
        task.save(update_fields=["progress", "updated_at"])
        messages.success(request, f'"{task.title}" marked {valid[progress].lower()}.')
    return redirect(request.POST.get("next") or "tasks:my_tasks")


@login_required
@require_POST
def task_delete(request, pk):
    """Deleting is a POST so a stray link or a page prefetch cannot wipe an entry."""
    task = _own_task(request, pk)
    title = task.title
    task.delete()
    messages.info(request, f'"{title}" deleted.')
    return redirect(request.POST.get("next") or "tasks:my_tasks")


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
    rows = sorted(
        ({"employee": emp, "tasks": items,
          "total": DailyTask.format_minutes(sum(t.minutes_spent for t in items))}
         for emp, items in by_employee.items()),
        key=lambda r: r["employee"].employee_id,
    )

    submitted = set(t.employee_id for t in tasks)
    missing = [e for e in User.objects.active_staff() if e.id not in submitted]

    return render(request, "tasks/task_board.html", {
        "day": day,
        "rows": rows,
        "day_total": DailyTask.format_minutes(sum(t.minutes_spent for t in tasks)),
        "missing": missing,
        "employees": User.objects.active_staff(),
        "emp_id": emp_id,
        "prev_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1),
    })


@login_required
def my_task_report(request):
    """The employee's own log, read back as a day, a week or a month."""
    from apps.attendance.views import _parse_date

    kind = request.GET.get("period", "week")
    if kind not in dict(PERIODS):
        kind = "week"
    anchor = _parse_date(request.GET.get("date"))
    start, end, label = period_bounds(kind, anchor)

    tasks = (DailyTask.objects.filter(employee=request.user, date__range=(start, end))
             .order_by("-date", "-created_at"))
    summary = summarise(tasks, start, end)
    worked = attendance_minutes(request.user, start, end)

    return render(request, "tasks/my_task_report.html", {
        "kind": kind, "periods": PERIODS,
        "start": start, "end": end, "label": label,
        "anchor": anchor,
        "prev": shift_period(kind, anchor, -1),
        "next": shift_period(kind, anchor, 1),
        "summary": summary,
        "coverage": coverage(summary["total_minutes"], worked),
        "show_days": kind != "day",
    })
