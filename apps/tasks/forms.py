from django import forms

from apps.accounts.forms import StyledFormMixin

from .models import DailyTask

# Five-minute steps: enough precision for a work log, and one tap on a phone
# instead of typing a number.
MINUTE_CHOICES = [(m, f"{m:02d}") for m in range(0, 60, 5)]


class DailyTaskForm(StyledFormMixin, forms.ModelForm):
    """Log a task with its length given as hours and minutes.

    The old form asked for a decimal number of hours, so an hour and five
    minutes meant working out 1.08 in your head. Two plain boxes remove that.
    """

    hours = forms.IntegerField(
        min_value=0, max_value=16, required=False, initial=1, label="Hours",
        widget=forms.NumberInput(attrs={"min": 0, "max": 16, "step": 1, "inputmode": "numeric"}),
    )
    minutes = forms.TypedChoiceField(
        choices=MINUTE_CHOICES, coerce=int, required=False, initial=0, label="Minutes",
    )

    class Meta:
        model = DailyTask
        fields = ["date", "title", "project", "progress", "details"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}),
                   "details": forms.Textarea(attrs={"rows": 2})}
        labels = {"title": "What did you work on", "details": "Details (optional)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["hours"].initial = self.instance.hours
            self.fields["minutes"].initial = self.instance.minutes - self.instance.minutes % 5
        self.fields["title"].widget.attrs["placeholder"] = "e.g. Fixed the invoice PDF bug"

    def clean(self):
        data = super().clean()
        total = (data.get("hours") or 0) * 60 + (data.get("minutes") or 0)
        if total <= 0:
            raise forms.ValidationError("How long did it take? Set at least five minutes.")
        if total > 16 * 60:
            raise forms.ValidationError("That is more than 16 hours - please split it up.")
        data["minutes_spent"] = total
        return data

    def save(self, commit=True):
        task = super().save(commit=False)
        task.minutes_spent = self.cleaned_data["minutes_spent"]
        if commit:
            task.save()
        return task
