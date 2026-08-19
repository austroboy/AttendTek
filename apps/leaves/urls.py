from django.urls import path

from . import views

app_name = "leaves"

urlpatterns = [
    path("me/", views.my_leaves, name="my_leaves"),
    path("me/<int:pk>/cancel/", views.cancel_leave, name="cancel"),
    path("team/", views.team_leaves, name="team"),
    path("review/", views.leave_review, name="review"),
    path("review/<int:pk>/<str:decision>/", views.leave_decide, name="decide"),
    path("types/", views.leave_type_list, name="types"),
]
