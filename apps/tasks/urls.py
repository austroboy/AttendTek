from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("me/", views.my_tasks, name="my_tasks"),
    path("me/report/", views.my_task_report, name="my_report"),
    path("me/<int:pk>/edit/", views.task_edit, name="task_edit"),
    path("me/<int:pk>/progress/<str:progress>/", views.task_set_progress, name="task_progress"),
    path("me/<int:pk>/delete/", views.task_delete, name="task_delete"),
    path("board/", views.task_board, name="task_board"),
]
