from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.report_home, name="home"),
    path("monthly/", views.monthly_sheet, name="monthly"),
    path("employee/", views.employee_report, name="employee"),
    path("late/", views.late_report, name="late"),
    path("trips/", views.outing_report, name="outings"),
    path("export/trips/", views.export_outings_csv, name="export_outings"),
    path("department/", views.department_report, name="department"),
    path("export/csv/", views.export_csv, name="export_csv"),
    path("export/excel/", views.export_excel, name="export_excel"),
]
