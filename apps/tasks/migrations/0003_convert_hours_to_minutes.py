"""Carry the old decimal hours across into whole minutes.

Tasks used to be logged as a decimal number of hours, which made anything that
was not a round figure awkward - an hour and five minutes had to be typed as
1.08. Minutes are exact, so the data moves over once and the awkwardness goes.
"""
from django.db import migrations


def hours_to_minutes(apps, schema_editor):
    DailyTask = apps.get_model("tasks", "DailyTask")
    for task in DailyTask.objects.all().iterator():
        minutes = int(round(float(task.hours_spent or 0) * 60))
        task.minutes_spent = max(minutes, 0)
        task.save(update_fields=["minutes_spent"])


def minutes_to_hours(apps, schema_editor):
    DailyTask = apps.get_model("tasks", "DailyTask")
    for task in DailyTask.objects.all().iterator():
        task.hours_spent = round((task.minutes_spent or 0) / 60, 2)
        task.save(update_fields=["hours_spent"])


class Migration(migrations.Migration):

    dependencies = [("tasks", "0002_dailytask_minutes_spent")]

    operations = [migrations.RunPython(hours_to_minutes, minutes_to_hours)]
