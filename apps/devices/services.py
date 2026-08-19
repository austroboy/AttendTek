"""Device sync orchestration - pulls punches down into the database."""
from __future__ import annotations

import csv
import io
from datetime import datetime

from django.utils import timezone

from apps.attendance.models import PunchLog
from apps.attendance.services import match_employee, record_punch, rebuild_day

from .models import Device, DeviceSyncLog
from .zk_service import DeviceError, fetch_attendance, fetch_users


def sync_device(device: Device) -> DeviceSyncLog:
    log = DeviceSyncLog.objects.create(device=device)
    touched = set()
    try:
        punches = fetch_attendance(device)
        log.fetched = len(punches)
        for p in punches:
            employee = match_employee(device_user_id=p.device_user_id)
            entry, created = record_punch(
                employee=employee,
                punch_time=p.timestamp,
                device_user_id=p.device_user_id,
                device=device,
                source=PunchLog.Source.DEVICE,
                raw_status=p.status,
            )
            if created:
                log.created += 1
                if employee:
                    touched.add((employee, p.timestamp.date()))
                else:
                    log.unmatched += 1
            else:
                log.skipped += 1
        for employee, day in touched:
            rebuild_day(employee, day)
        log.success = True
        log.message = f"{log.created} new punches imported."
    except DeviceError as exc:
        log.success = False
        log.message = str(exc)
    except Exception as exc:  # pragma: no cover
        log.success = False
        log.message = f"Unexpected error: {exc}"
    log.finished_at = timezone.now()
    log.save()

    device.last_sync_at = log.finished_at
    device.last_sync_status = ("OK - " if log.success else "FAILED - ") + log.message[:150]
    device.save(update_fields=["last_sync_at", "last_sync_status"])
    return log


def pull_card_numbers(device: Device) -> dict:
    """Read card numbers from the device user list into the employee records."""
    from apps.accounts.models import User

    result = {"matched": 0, "updated": 0, "unknown": []}
    for du in fetch_users(device):
        emp = User.objects.filter(device_user_id=du.device_user_id).first()
        if not emp and du.card_no:
            emp = User.objects.filter(rfid_card_no=du.card_no).first()
        if not emp:
            result["unknown"].append(du)
            continue
        result["matched"] += 1
        changed = []
        if du.card_no and du.card_no != "0" and emp.rfid_card_no != du.card_no:
            emp.rfid_card_no = du.card_no
            changed.append("rfid_card_no")
        if not emp.device_user_id:
            emp.device_user_id = du.device_user_id
            changed.append("device_user_id")
        if changed:
            emp.save(update_fields=changed)
            result["updated"] += 1
    return result


def import_punches_csv(file_obj, device=None) -> dict:
    """Import punches from a CSV file (a fallback when the device is offline)."""
    text = io.TextIOWrapper(file_obj, encoding="utf-8-sig", errors="ignore")
    reader = csv.DictReader(text)
    stats = {"rows": 0, "created": 0, "skipped": 0, "unmatched": 0, "errors": []}
    touched = set()
    for row in reader:
        stats["rows"] += 1
        raw_time = (row.get("punch_time") or row.get("time") or row.get("datetime") or "").strip()
        card = (row.get("card_no") or row.get("card") or "").strip()
        duid = (row.get("device_user_id") or row.get("user_id") or "").strip()
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M"):
            try:
                dt = datetime.strptime(raw_time, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            stats["errors"].append(f"Row {stats['rows']}: could not read the time -> {raw_time}")
            continue
        employee = match_employee(card_no=card, device_user_id=duid)
        entry, created = record_punch(
            employee=employee, punch_time=dt, card_no=card, device_user_id=duid,
            device=device, source=PunchLog.Source.IMPORT,
        )
        if created:
            stats["created"] += 1
            if employee:
                touched.add((employee, dt.date()))
            else:
                stats["unmatched"] += 1
        else:
            stats["skipped"] += 1
    for employee, day in touched:
        rebuild_day(employee, day)
    return stats
