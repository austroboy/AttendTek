from django.db import models
from django.utils import timezone


class Device(models.Model):
    """Configuration for a ZKTeco F18 (or any other ZK push/pull device)."""

    name = models.CharField(max_length=60, help_text="e.g. Main Gate F18")
    ip_address = models.GenericIPAddressField()
    port = models.PositiveIntegerField(default=4370)
    comm_password = models.CharField(max_length=32, blank=True, help_text="Device COMM key (leave blank if it is 0)")
    timeout = models.PositiveIntegerField(default=10)
    force_udp = models.BooleanField(default=False)
    location = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)
    clear_after_sync = models.BooleanField(
        default=False, help_text="Clear the device log after a successful sync (use with care)"
    )
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.ip_address}:{self.port})"


class DeviceSyncLog(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="sync_logs")
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    fetched = models.PositiveIntegerField(default=0)
    created = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    unmatched = models.PositiveIntegerField(default=0, help_text="Punches that matched no employee")
    success = models.BooleanField(default=False)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.device.name} @ {self.started_at:%d %b %Y %I:%M %p}"
