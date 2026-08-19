from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied
from functools import wraps


def manager_required(view_func):
    """Only admins and HR can open this view."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.shortcuts import redirect
            return redirect("accounts:login")
        if not request.user.is_manager:
            raise PermissionDenied("You do not have permission to view this page.")
        return view_func(request, *args, **kwargs)

    return _wrapped


login_required_any = user_passes_test(lambda u: u.is_authenticated, login_url="accounts:login")
