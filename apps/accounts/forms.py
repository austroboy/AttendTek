from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import Department, Designation, Shift, User

INPUT = "field"


class StyledFormMixin:
    """Applies the same CSS classes to every form widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("class", "check")
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault("class", "field select")
            else:
                w.attrs.setdefault("class", INPUT)
            if isinstance(w, forms.DateInput):
                w.input_type = "date"
            if isinstance(w, forms.TimeInput):
                w.input_type = "time"
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault("rows", 3)


class LoginForm(StyledFormMixin, AuthenticationForm):
    username = forms.CharField(label="Employee ID or username")


class EmployeeForm(StyledFormMixin, forms.ModelForm):
    """Employee add/edit form used on the admin dashboard - the RFID card ID is set here."""

    password = forms.CharField(
        widget=forms.PasswordInput, required=False,
        help_text="Required for a new employee. Leave blank when editing to keep the current password.",
    )

    class Meta:
        model = User
        fields = [
            "employee_id", "username", "first_name", "last_name", "email", "phone",
            "role", "department", "designation", "shift", "manager", "work_policy",
            "rfid_card_no", "device_user_id", "card_issued_on",
            "joining_date", "photo", "is_attendance_tracked", "is_active",
        ]
        widgets = {
            "card_issued_on": forms.DateInput(attrs={"type": "date"}),
            "joining_date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "rfid_card_no": "RFID card ID",
            "device_user_id": "Device user ID (F18)",
            "is_attendance_tracked": "Track attendance for this employee",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = User.objects.filter(is_active=True)
        self.fields["shift"].queryset = Shift.objects.all()
        if not self.instance.pk:
            self.fields["password"].required = True
        self.fields["rfid_card_no"].widget.attrs["placeholder"] = "e.g. 0012345678"

    def clean_rfid_card_no(self):
        card = (self.cleaned_data.get("rfid_card_no") or "").strip()
        if not card:
            return None
        qs = User.objects.filter(rfid_card_no__iexact=card)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            owner = qs.first()
            raise forms.ValidationError(f"This card is already assigned to {owner.display_name}.")
        return card

    def save(self, commit=True):
        user = super().save(commit=False)
        pwd = self.cleaned_data.get("password")
        if pwd:
            user.set_password(pwd)
        if commit:
            user.save()
        return user


class CardAssignForm(StyledFormMixin, forms.ModelForm):
    """Quick form for assigning just the card."""

    class Meta:
        model = User
        fields = ["rfid_card_no", "device_user_id", "card_issued_on"]
        widgets = {"card_issued_on": forms.DateInput(attrs={"type": "date"})}
        labels = {"rfid_card_no": "RFID card ID", "device_user_id": "Device user ID"}


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "photo"]


class DepartmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "code"]


class DesignationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Designation
        fields = ["title"]


class ShiftForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Shift
        fields = [
            "name", "start_time", "end_time", "late_after", "required_hours",
            "half_day_hours", "min_out_gap_minutes", "weekend_days", "is_default",
        ]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "late_after": forms.TimeInput(attrs={"type": "time"}),
        }
