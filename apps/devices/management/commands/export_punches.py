"""Export punches to CSV so they can be uploaded to a cloud deployment.

The ZKTeco device lives on the office LAN, which a cloud server cannot reach.
Run this on an office machine that can see the device, then upload the CSV on
the live site under Devices -> CSV import.

    python manage.py export_punches --days 2 --out punches.csv
"""
import csv
from datetime import timedelta

from django.core.management.base import BaseCommand

from apps.devices.models import Device
from apps.devices.zk_service import DeviceError, fetch_attendance
from apps.utils import now


class Command(BaseCommand):
    help = "Read punches from the devices and write them to a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=1, help="How many days back to include")
        parser.add_argument("--out", default="punches.csv", help="Output file name")

    def handle(self, *args, **options):
        cutoff = now() - timedelta(days=options["days"])
        rows = []
        for device in Device.objects.filter(is_active=True):
            try:
                for punch in fetch_attendance(device):
                    if punch.timestamp >= cutoff:
                        rows.append([punch.device_user_id, punch.timestamp.strftime("%Y-%m-%d %H:%M:%S")])
            except DeviceError as exc:
                self.stderr.write(self.style.ERROR(f"{device.name}: {exc}"))

        rows.sort(key=lambda r: r[1])
        with open(options["out"], "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["device_user_id", "punch_time"])
            writer.writerows(rows)
        self.stdout.write(self.style.SUCCESS(
            f"{len(rows)} punches written to {options['out']} - upload it under Devices > CSV import."
        ))
