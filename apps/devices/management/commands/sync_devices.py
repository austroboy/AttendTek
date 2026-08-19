"""Cron: */10 * * * * python manage.py sync_devices"""
from django.core.management.base import BaseCommand

from apps.devices.models import Device
from apps.devices.services import sync_device


class Command(BaseCommand):
    help = "Pull punch logs from every active ZKTeco device."

    def add_arguments(self, parser):
        parser.add_argument("--device", type=int, help="Only sync the device with this id")

    def handle(self, *args, **options):
        qs = Device.objects.filter(is_active=True)
        if options.get("device"):
            qs = qs.filter(pk=options["device"])
        if not qs.exists():
            self.stdout.write(self.style.WARNING("No active devices configured."))
            return
        for device in qs:
            log = sync_device(device)
            style = self.style.SUCCESS if log.success else self.style.ERROR
            self.stdout.write(style(f"{device.name}: {log.message}"))
