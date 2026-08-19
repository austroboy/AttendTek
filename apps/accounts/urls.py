from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.AppLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile, name="profile"),
    path("employees/", views.employee_list, name="employee_list"),
    path("employees/add/", views.employee_create, name="employee_create"),
    path("employees/<int:pk>/", views.employee_detail, name="employee_detail"),
    path("employees/<int:pk>/edit/", views.employee_edit, name="employee_edit"),
    path("cards/", views.card_assign_board, name="card_board"),
    path("settings/", views.settings_home, name="settings"),
    path("settings/shift/add/", views.shift_form, name="shift_create"),
    path("settings/shift/<int:pk>/", views.shift_form, name="shift_edit"),
    path("settings/department/add/", views.department_form, name="department_create"),
    path("settings/designation/add/", views.designation_form, name="designation_create"),
]
