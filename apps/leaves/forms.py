from django import forms

from apps.accounts.forms import StyledFormMixin

from .models import LeaveRequest, LeaveType


class LeaveRequestForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ["leave_type", "start_date", "end_date", "is_half_day",
                  "reason", "contact_during_leave", "attachment"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "reason": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "leave_type": "Leave type",
            "start_date": "From", "end_date": "To",
            "is_half_day": "Half day", "reason": "Reason",
            "contact_during_leave": "Contact number while on leave",
        }

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "The end date cannot be before the start date.")
        return data


class LeaveDecisionForm(StyledFormMixin, forms.Form):
    review_note = forms.CharField(required=False, max_length=200, label="Note (optional)")


class LeaveTypeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = ["name", "code", "annual_quota", "is_paid", "color"]
