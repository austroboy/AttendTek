"""Slowing down password guessing.

The site sits on the open internet with a login form, and the server logs
already show strangers trying SSH names at random. A 15-person office has no
lockout policy and no security team, so the protection has to be automatic and
has to fail in the safe direction: brief lockouts that clear themselves, never
a permanent one that needs an admin at 9am.
"""
from datetime import timedelta

from django.db import models
from django.utils import timezone

MAX_ATTEMPTS = 8
WINDOW_MINUTES = 15
LOCK_MINUTES = 15


class LoginAttempt(models.Model):
    """One failed sign-in. Successful ones clear the record."""

    username = models.CharField(max_length=150, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"failed login for {self.username} at {self.created_at:%d %b %H:%M}"


def _window_start():
    return timezone.now() - timedelta(minutes=WINDOW_MINUTES)


def recent_failures(username: str, ip: str | None) -> int:
    """Failures in the last few minutes, counted per name and per address.

    Both matter: one attacker trying many names from one address, and many
    addresses trying one name, are the two shapes this needs to catch.
    """
    window = _window_start()
    by_name = LoginAttempt.objects.filter(
        username__iexact=username, created_at__gte=window).count()
    by_ip = LoginAttempt.objects.filter(
        ip_address=ip, created_at__gte=window).count() if ip else 0
    return max(by_name, by_ip)


def is_locked(username: str, ip: str | None) -> bool:
    return recent_failures(username, ip) >= MAX_ATTEMPTS


def minutes_left(username: str, ip: str | None) -> int:
    """How long until they can try again."""
    last = LoginAttempt.objects.filter(
        models.Q(username__iexact=username) | models.Q(ip_address=ip)
    ).order_by("-created_at").first()
    if not last:
        return 0
    unlock_at = last.created_at + timedelta(minutes=LOCK_MINUTES)
    remaining = (unlock_at - timezone.now()).total_seconds() / 60
    return max(1, int(remaining + 0.5))


def record_failure(username: str, ip: str | None, user_agent: str = "") -> None:
    LoginAttempt.objects.create(
        username=(username or "")[:150], ip_address=ip, user_agent=(user_agent or "")[:200]
    )


def clear(username: str, ip: str | None) -> None:
    """A correct password means this was a person, not a script."""
    LoginAttempt.objects.filter(
        models.Q(username__iexact=username) | models.Q(ip_address=ip)
    ).delete()


def prune(days: int = 7) -> int:
    """Old attempts are noise; the nightly job clears them out."""
    cutoff = timezone.now() - timedelta(days=days)
    return LoginAttempt.objects.filter(created_at__lt=cutoff).delete()[0]
