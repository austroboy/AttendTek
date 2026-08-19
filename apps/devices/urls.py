from django.urls import path

from . import views

app_name = "devices"

urlpatterns = [
    path("", views.device_list, name="list"),
    path("add/", views.device_form, name="create"),
    path("<int:pk>/edit/", views.device_form, name="edit"),
    path("<int:pk>/sync/", views.device_sync, name="sync"),
    path("<int:pk>/pull-cards/", views.device_pull_cards, name="pull_cards"),
    path("<int:pk>/set-time/", views.device_set_time, name="set_time"),
    path("<int:pk>/push/<int:employee_id>/", views.device_push_user, name="push_user"),
    path("import/", views.punch_import, name="import"),
]
