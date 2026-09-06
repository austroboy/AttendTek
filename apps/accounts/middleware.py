"""Sign out anyone who was deactivated while they were still logged in.

Django only checks `is_active` at the moment of signing in. An employee who is
deactivated at 3pm keeps full access in whatever tab they already have open
until their session expires, which for an attendance system is exactly the
wrong behaviour.
"""
from django.contrib.auth import logout
from django.contrib import messages
from django.shortcuts import redirect


class DeactivatedUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not user.is_active:
            logout(request)
            messages.error(
                request,
                "This account has been deactivated. Please contact your office admin.",
            )
            return redirect("accounts:login")
        return self.get_response(request)
