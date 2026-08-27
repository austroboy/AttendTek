"""Small helpers - USE_TZ is False, so we work with local naive datetimes."""
from datetime import date as date_cls, datetime


def now() -> datetime:
    """The current local naive datetime."""
    return datetime.now().replace(microsecond=0)


def today() -> date_cls:
    return datetime.now().date()


def paginate(request, queryset, per_page=25, param="page"):
    """One page of a queryset, sized from the request.

    Long lists are the quiet way a small app gets slow: a year of punches is
    tens of thousands of rows, and rendering them all costs the server memory
    it does not need to spend. Everything that can grow without limit goes
    through here.
    """
    from django.core.paginator import Paginator

    try:
        per_page = int(request.GET.get("per_page", per_page))
    except (TypeError, ValueError):
        pass
    per_page = max(10, min(per_page, 200))

    paginator = Paginator(queryset, per_page)
    number = request.GET.get(param) or 1
    try:
        page = paginator.page(number)
    except Exception:
        # Out of range or not a number - show the first page rather than a 404.
        page = paginator.page(1)
    return page
