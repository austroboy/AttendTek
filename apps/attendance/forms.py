from datetime import datetime

from django import forms
from django.utils import timezone

from apps.utils import now as app_now, today as app_today

from apps.accounts.forms import StyledFormMixin
from apps.accounts.models import User

from .models import (AttendanceCorrection, DailyAttendance, Holiday, HomeOfficeEntry,
                     OfficeLocation, Outing, PunchLog, PunchPolicy)


class HomeOfficeStartForm(StyledFormMixin, forms.ModelForm):
    """The employee picks home office and logs an in time."""

    in_time = forms.TimeField(label="In time", widget=forms.TimeInput(attrs={"type": "time"}))

    class Meta:
        model = HomeOfficeEntry
        fields = ["date", "reason"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}
        labels = {"date": "Date", "reason": "Reason"}

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        self.fields["date"].initial = app_today()
        self.fields["in_time"].initial = app_now().time().replace(second=0, microsecond=0)

    def clean(self):
        data = super().clean()
        day, in_time = data.get("date"), data.get("in_time")
        if self.employee and day and HomeOfficeEntry.objects.filter(
            employee=self.employee, date=day
        ).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("There is already a home office entry for this date.")
        if day and in_time:
            data["check_in"] = datetime.combine(day, in_time)
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.employee = self.employee
        obj.check_in = self.cleaned_data["check_in"]
        # Home office does not need approval - it counts straight away.
        # An admin can still reject a wrong entry from the Home office log.
        obj.status = HomeOfficeEntry.Status.APPROVED
        if commit:
            obj.save()
        return obj


class HomeOfficeOutForm(StyledFormMixin, forms.ModelForm):
    out_time = forms.TimeField(label="Out time", widget=forms.TimeInput(attrs={"type": "time"}))

    class Meta:
        model = HomeOfficeEntry
        fields = ["work_summary"]
        labels = {"work_summary": "Short summary of today's work"}

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.check_out = datetime.combine(obj.date, self.cleaned_data["out_time"])
        if commit:
            obj.save()
        return obj


class HomeOfficeReviewForm(StyledFormMixin, forms.Form):
    review_note = forms.CharField(required=False, max_length=200, label="Note (optional)")


class ManualPunchForm(StyledFormMixin, forms.Form):
    """Used when someone forgets their card or the device fails."""

    employee = forms.ModelChoiceField(queryset=User.objects.none(), label="Employee")
    punch_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Date")
    punch_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}), label="Time")
    note = forms.CharField(required=False, max_length=160, label="Reason / note")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = User.objects.active_staff()
        self.fields["punch_date"].initial = app_today()

    @property
    def punch_datetime(self):
        return datetime.combine(self.cleaned_data["punch_date"], self.cleaned_data["punch_time"])


class AttendanceOverrideForm(StyledFormMixin, forms.ModelForm):
    in_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}))
    out_time = forms.TimeField(required=False, widget=forms.TimeInput(attrs={"type": "time"}))

    class Meta:
        model = DailyAttendance
        fields = ["status", "mode", "remarks", "is_manual_override"]
        labels = {"is_manual_override": "Keep manual override on (stops automatic recalculation)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.check_in:
            self.fields["in_time"].initial = self.instance.check_in.time()
        if self.instance.check_out:
            self.fields["out_time"].initial = self.instance.check_out.time()


class HolidayForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["date", "title", "is_optional"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class OutingForm(StyledFormMixin, forms.ModelForm):
    """What the employee fills in for one trip out of the office."""

    class Meta:
        model = Outing
        fields = ["purpose", "destination", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}
        labels = {
            "purpose": "Purpose",
            "destination": "Where did you go?",
            "note": "What was it for?",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["purpose"].choices = [
            c for c in Outing.Purpose.choices if c[0] != Outing.Purpose.UNSPECIFIED
        ]
        self.fields["destination"].widget.attrs["placeholder"] = "e.g. Client office, Gulshan"


class OutingAdminForm(StyledFormMixin, forms.ModelForm):
    """Admins can also decide whether the time counts towards the hours."""

    class Meta:
        model = Outing
        fields = ["purpose", "destination", "note", "counts_as_work"]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}
        labels = {"counts_as_work": "Count this time as working hours"}

    def save(self, commit=True):
        obj = super().save(commit=False)
        # Setting the checkbox by hand overrides what the purpose would imply.
        obj.is_admin_adjusted = obj.counts_as_work != (obj.purpose in Outing.PAID_PURPOSES)
        if commit:
            obj.save()
        return obj


class SelfPunchForm(forms.Form):
    """Hidden fields the browser fills in before the punch is submitted."""

    latitude = forms.DecimalField(required=False, widget=forms.HiddenInput)
    longitude = forms.DecimalField(required=False, widget=forms.HiddenInput)
    accuracy_m = forms.IntegerField(required=False, min_value=0, widget=forms.HiddenInput)
    location_error = forms.CharField(required=False, widget=forms.HiddenInput)
    note = forms.CharField(
        required=False, max_length=160, label="Note (optional)",
        widget=forms.TextInput(attrs={"placeholder": "e.g. at the client site"}),
    )
    mode = forms.CharField(required=False, widget=forms.HiddenInput)


class OfficeLocationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = OfficeLocation
        fields = ["name", "latitude", "longitude", "radius_m", "address", "is_active"]
        labels = {"radius_m": "Radius in metres"}


class PunchPolicyForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PunchPolicy
        fields = ["self_punch_enabled", "require_location", "allow_outside_office",
                  "max_accuracy_m", "notice"]


class CorrectionRequestForm(StyledFormMixin, forms.ModelForm):
    """An employee asking for a day to be fixed."""

    class Meta:
        model = AttendanceCorrection
        fields = ["date", "requested_in", "requested_out", "reason", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "requested_in": forms.TimeInput(attrs={"type": "time"}),
            "requested_out": forms.TimeInput(attrs={"type": "time"}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "date": "Which day",
            "requested_in": "Actual in time",
            "requested_out": "Actual out time",
            "reason": "What went wrong",
            "note": "What actually happened",
        }
        help_texts = {
            "requested_in": "Leave blank to keep what is already recorded",
            "requested_out": "Leave blank to keep what is already recorded",
        }

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        from apps.utils import today
        self.fields["date"].widget.attrs["max"] = today().isoformat()

    def clean_date(self):
        from apps.utils import today

        day = self.cleaned_data["date"]
        if day > today():
            raise forms.ValidationError("You cannot ask to correct a day that has not happened.")
        if self.employee and self.employee.joining_date and day < self.employee.joining_date:
            raise forms.ValidationError("That date is before you joined.")
        return day

    def clean(self):
        data = super().clean()
        if not data.get("requested_in") and not data.get("requested_out"):
            raise forms.ValidationError("Give at least one time - the in time, the out time, or both.")
        if (data.get("requested_in") and data.get("requested_out")
                and data["requested_out"] <= data["requested_in"]):
            raise forms.ValidationError("The out time has to be after the in time.")

        day = data.get("date")
        if self.employee and day and AttendanceCorrection.objects.filter(
            employee=self.employee, date=day, status=AttendanceCorrection.Status.PENDING
        ).exists():
            raise forms.ValidationError(
                "You already have a request waiting for that day.")
        return data


class CorrectionDecisionForm(StyledFormMixin, forms.Form):
    review_note = forms.CharField(required=False, max_length=200, label="Note (optional)")
