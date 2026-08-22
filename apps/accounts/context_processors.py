from django.conf import settings


def sidebar_badges(request):
    """Branding and the small counters shown on the sidebar."""
    data = {
        "site_name": getattr(settings, "SITE_NAME", "Attendance"),
        "site_tagline": getattr(settings, "SITE_TAGLINE", ""),
    }
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return data

    from apps.attendance.models import HomeOfficeEntry
    from apps.leaves.models import LeaveRequest
    from datetime import timedelta

    from apps.utils import today

    day = today()
    data["out_today_count"] = LeaveRequest.objects.filter(
        status=LeaveRequest.Status.APPROVED, start_date__lte=day, end_date__gte=day
    ).count()

    from apps.attendance.models import Outing

    data["my_unlabelled_trips"] = Outing.objects.filter(
        employee=user, purpose=Outing.Purpose.UNSPECIFIED).count()

    if user.is_manager:
        data["unexplained_total"] = Outing.objects.filter(
            purpose=Outing.Purpose.UNSPECIFIED, date__gte=day - timedelta(days=30)).count()
        data["pending_leaves"] = LeaveRequest.objects.filter(status="PENDING").count()
        data["pending_home_office"] = HomeOfficeEntry.objects.filter(status="PENDING").count()
    return data
