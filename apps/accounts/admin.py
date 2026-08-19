from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Department, Designation, Shift, User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    list_display = ("employee_id", "display_name", "rfid_card_no", "department", "role", "is_active")
    list_filter = ("role", "department", "work_policy", "is_active")
    search_fields = ("employee_id", "username", "first_name", "last_name", "rfid_card_no")
    fieldsets = UserAdmin.fieldsets + (
        ("Employee info", {
            "fields": ("employee_id", "role", "department", "designation", "shift", "manager",
                       "phone", "joining_date", "photo", "work_policy", "is_attendance_tracked")
        }),
        ("RFID / Device", {"fields": ("rfid_card_no", "device_user_id", "card_issued_on")}),
    )


admin.site.register([Department, Designation, Shift])
admin.site.site_header = "Office Attendance Admin"
