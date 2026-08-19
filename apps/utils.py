"""Small helpers - USE_TZ is False, so we work with local naive datetimes."""
from datetime import date as date_cls, datetime


def now() -> datetime:
    """The current local naive datetime."""
    return datetime.now().replace(microsecond=0)


def today() -> date_cls:
    return datetime.now().date()
