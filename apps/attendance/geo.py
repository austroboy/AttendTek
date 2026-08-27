"""Working out where a punch came from.

Browser geolocation is useful but not proof - a determined person can feed the
browser a fake position. So rather than treating coordinates as truth, every
punch is measured against the offices on record and labelled plainly: at the
office, or away from it and by how far. Managers then read a sentence, not a
pair of decimals, and anything odd stands out on its own.
"""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000


def distance_metres(lat1, lon1, lat2, lon2) -> int:
    """Great-circle distance between two points, in metres (haversine)."""
    lat1, lon1, lat2, lon2 = (radians(float(v)) for v in (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return int(round(2 * EARTH_RADIUS_M * asin(sqrt(a))))


def nearest_office(latitude, longitude):
    """The closest active office and how far away it is.

    Returns (office, distance_m) or (None, None) when no office is on record.
    """
    from .models import OfficeLocation

    offices = OfficeLocation.objects.filter(is_active=True)
    best, best_distance = None, None
    for office in offices:
        d = distance_metres(latitude, longitude, office.latitude, office.longitude)
        if best_distance is None or d < best_distance:
            best, best_distance = office, d
    return best, best_distance


def classify(latitude, longitude, accuracy_m, policy):
    """Turn a raw reading into a status, an office and a distance."""
    from .models import PunchLog

    S = PunchLog.LocationStatus
    if latitude is None or longitude is None:
        return S.MISSING, None, None

    office, distance = nearest_office(latitude, longitude)
    if office is None:
        status = S.UNKNOWN
    elif distance <= office.radius_m:
        status = S.INSIDE
    else:
        status = S.OUTSIDE

    # A vague reading can put someone "inside" the office from the next street,
    # so say so rather than quietly trusting it.
    if accuracy_m and policy and accuracy_m > policy.max_accuracy_m and status != S.OUTSIDE:
        status = S.WEAK
    return status, office, distance
