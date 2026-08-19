from django.contrib import admin

from .models import DailyTask


@admin.register(DailyTask)
class DailyTaskAdmin(admin.ModelAdmin):
    list_display = ("date", "employee", "title", "hours_spent", "progress")
    list_filter = ("progress", "date")
    search_fields = ("title", "employee__employee_id")
