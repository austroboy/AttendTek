from django import forms

from apps.accounts.forms import StyledFormMixin

from .models import DailyTask


class DailyTaskForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DailyTask
        fields = ["date", "title", "project", "hours_spent", "progress", "details"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}),
                   "details": forms.Textarea(attrs={"rows": 2})}
        labels = {"title": "What did you work on", "hours_spent": "Hours spent", "details": "Details (optional)"}
