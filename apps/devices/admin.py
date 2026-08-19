from django.contrib import admin

from .models import Device, DeviceSyncLog


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "ip_address", "port", "is_active", "last_sync_at")


admin.site.register(DeviceSyncLog)
