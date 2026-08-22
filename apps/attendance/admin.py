from django.contrib import admin

from .models import DailyAttendance, Holiday, HomeOfficeEntry, Outing, PunchLog


@admin.register(PunchLog)
class PunchLogAdmin(admin.ModelAdmin):
    list_display = ("punch_time", "employee", "card_no", "source", "is_matched", "device")
    list_filter = ("source", "is_matched", "device")
    search_fields = ("card_no", "device_user_id", "employee__employee_id")
    date_hierarchy = "punch_time"


@admin.register(DailyAttendance)
class DailyAttendanceAdmin(admin.ModelAdmin):
    list_display = ("date", "employee", "check_in", "required_out", "check_out", "status", "worked_display")
    list_filter = ("status", "mode", "is_late", "is_early_out")
    search_fields = ("employee__employee_id", "employee__first_name")
    date_hierarchy = "date"


@admin.register(Outing)
class OutingAdmin(admin.ModelAdmin):
    list_display = ("date", "employee", "left_at", "returned_at", "minutes", "purpose", "counts_as_work")
    list_filter = ("purpose", "counts_as_work", "date")
    search_fields = ("employee__employee_id", "destination", "note")
    date_hierarchy = "date"


admin.site.register([Holiday, HomeOfficeEntry])
