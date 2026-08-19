from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import manager_required

from .forms import DeviceForm, PunchImportForm
from .models import Device, DeviceSyncLog
from .services import import_punches_csv, pull_card_numbers, sync_device
from .zk_service import ZK_AVAILABLE, DeviceError, push_user, sync_device_time


@manager_required
def device_list(request):
    return render(request, "devices/device_list.html", {
        "devices": Device.objects.all(),
        "logs": DeviceSyncLog.objects.select_related("device")[:12],
        "zk_available": ZK_AVAILABLE,
        "import_form": PunchImportForm(),
    })


@manager_required
def device_form(request, pk=None):
    device = get_object_or_404(Device, pk=pk) if pk else None
    form = DeviceForm(request.POST or None, instance=device)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Device saved.")
        return redirect("devices:list")
    return render(request, "devices/device_form.html", {"form": form, "device": device})


@manager_required
def device_sync(request, pk):
    device = get_object_or_404(Device, pk=pk)
    log = sync_device(device)
    if log.success:
        messages.success(request, f"{device.name}: {log.created} new punches, {log.skipped} already recorded.")
        if log.unmatched:
            messages.warning(request, f"{log.unmatched} punches did not match any employee.")
    else:
        messages.error(request, f"{device.name}: {log.message}")
    return redirect("devices:list")


@manager_required
def device_pull_cards(request, pk):
    device = get_object_or_404(Device, pk=pk)
    try:
        res = pull_card_numbers(device)
        messages.success(request, f"{res['matched']} employees matched, {res['updated']} card IDs updated.")
        if res["unknown"]:
            messages.info(request, f"{len(res['unknown'])} device users are not in the database.")
    except DeviceError as exc:
        messages.error(request, str(exc))
    return redirect("devices:list")


@manager_required
def device_push_user(request, pk, employee_id):
    from apps.accounts.models import User

    device = get_object_or_404(Device, pk=pk)
    emp = get_object_or_404(User, pk=employee_id)
    try:
        push_user(device, emp)
        messages.success(request, f"{emp.display_name} was pushed to {device.name}.")
    except DeviceError as exc:
        messages.error(request, str(exc))
    return redirect("accounts:employee_detail", pk=emp.pk)


@manager_required
def device_set_time(request, pk):
    device = get_object_or_404(Device, pk=pk)
    try:
        now = sync_device_time(device)
        messages.success(request, f"Device time set to: {now:%d %b %Y %I:%M %p}")
    except DeviceError as exc:
        messages.error(request, str(exc))
    return redirect("devices:list")


@manager_required
def punch_import(request):
    form = PunchImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        stats = import_punches_csv(request.FILES["csv_file"])
        messages.success(
            request,
            f"{stats['rows']} rows read — {stats['created']} notun, "
            f"{stats['skipped']} duplicates, {stats['unmatched']} unmatched.",
        )
        for err in stats["errors"][:5]:
            messages.warning(request, err)
    return redirect("devices:list")
