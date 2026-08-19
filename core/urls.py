from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import root_redirect

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", root_redirect, name="root"),
    path("accounts/", include("apps.accounts.urls")),
    path("attendance/", include("apps.attendance.urls")),
    path("devices/", include("apps.devices.urls")),
    path("leaves/", include("apps.leaves.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("reports/", include("apps.reports.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
