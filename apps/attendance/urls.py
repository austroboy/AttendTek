from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    # admin / HR
    path("dashboard/", views.dashboard, name="dashboard"),
    path("sheet/", views.attendance_sheet, name="sheet"),
    path("record/<int:pk>/edit/", views.attendance_edit, name="record_edit"),
    path("punches/", views.punch_log_list, name="punch_logs"),
    path("punches/<int:pk>/link/", views.punch_log_link, name="punch_link"),
    path("recalculate/", views.recalculate, name="recalculate"),
    path("home-office/review/", views.home_office_review, name="home_office_review"),
    path("home-office/<int:pk>/<str:decision>/", views.home_office_decide, name="home_office_decide"),
    path("holidays/", views.holiday_list, name="holidays"),
    # employee
    path("me/", views.my_portal, name="my_portal"),
    path("me/attendance/", views.my_attendance, name="my_attendance"),
    path("me/home-office/", views.home_office, name="home_office"),
    path("me/trips/", views.my_outings, name="my_outings"),
    path("trips/<int:pk>/edit/", views.outing_edit, name="outing_edit"),
]
