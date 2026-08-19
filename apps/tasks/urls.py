from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("me/", views.my_tasks, name="my_tasks"),
    path("me/<int:pk>/delete/", views.task_delete, name="task_delete"),
    path("board/", views.task_board, name="task_board"),
]
