"""Sidebar helpers: highlight the item the user is currently on."""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def nav_active(context, *view_names):
    """Return "active" when the current page matches one of the given view names.

    Usage in a template:
        <a class="nav {% nav_active 'accounts:employee_list' 'accounts:employee_detail' %}" ...>

    Pass every view that belongs under the same menu item, so the item stays
    highlighted on its detail and edit pages too.
    """
    request = context.get("request")
    match = getattr(request, "resolver_match", None)
    if match is None:
        return ""
    current = match.view_name  # e.g. "accounts:employee_detail"
    return "active" if current in view_names else ""
