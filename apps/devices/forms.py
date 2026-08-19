from django import forms

from apps.accounts.forms import StyledFormMixin

from .models import Device


class DeviceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Device
        fields = ["name", "ip_address", "port", "comm_password", "timeout",
                  "force_udp", "location", "clear_after_sync", "is_active"]
        labels = {"ip_address": "Device IP", "comm_password": "COMM key"}


class PunchImportForm(StyledFormMixin, forms.Form):
    """Import a CSV/DAT file exported from the device."""

    csv_file = forms.FileField(
        label="CSV file",
        help_text="Columns: card_no or device_user_id, and punch_time (YYYY-MM-DD HH:MM:SS)",
    )
