from datetime import datetime

from django import forms
from django.utils import timezone

from apps.utils import now as app_now, today as app_today

from apps.accounts.forms import StyledFormMixin
from apps.accounts.models import User

from .models import DailyAttendance, Holiday, HomeOfficeEntry, PunchLog


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
