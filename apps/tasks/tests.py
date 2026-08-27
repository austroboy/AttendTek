"""Task logging - the length of a task is kept in whole minutes."""
from datetime import date, time

from django.test import TestCase

from apps.accounts.models import Shift, User

from .forms import DailyTaskForm
from .models import DailyTask


class TaskDurationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), is_default=True,
        )
        cls.emp = User.objects.create_user(
            username="nabila", password="pw", employee_id="EMP-030", shift=cls.shift
        )

    def make(self, hours, minutes):
        form = DailyTaskForm({
            "date": date(2026, 8, 27), "title": "Invoice fix", "project": "Internal",
            "progress": "DONE", "details": "", "hours": hours, "minutes": minutes,
        })
        self.assertTrue(form.is_valid(), form.errors)
        task = form.save(commit=False)
        task.employee = self.emp
        task.save()
        return task

    def test_one_hour_five_minutes(self):
        """The case that could not be entered before."""
        task = self.make(1, 5)
        self.assertEqual(task.minutes_spent, 65)
        self.assertEqual(task.duration_display, "1h 05m")

    def test_minutes_only(self):
        task = self.make(0, 45)
        self.assertEqual(task.minutes_spent, 45)
        self.assertEqual(task.duration_display, "45m")

    def test_whole_hours_read_cleanly(self):
        task = self.make(3, 0)
        self.assertEqual(task.duration_display, "3h")

    def test_zero_length_is_rejected(self):
        form = DailyTaskForm({
            "date": date(2026, 8, 27), "title": "Nothing", "progress": "DONE",
            "hours": 0, "minutes": 0,
        })
        self.assertFalse(form.is_valid())

    def test_absurd_length_is_rejected(self):
        form = DailyTaskForm({
            "date": date(2026, 8, 27), "title": "Everything", "progress": "DONE",
            "hours": 16, "minutes": 30,
        })
        self.assertFalse(form.is_valid())

    def test_editing_shows_the_original_length_back(self):
        task = self.make(2, 20)
        form = DailyTaskForm(instance=task)
        self.assertEqual(form.fields["hours"].initial, 2)
        self.assertEqual(form.fields["minutes"].initial, 20)

    def test_day_total_adds_up(self):
        self.make(1, 5)
        self.make(0, 25)
        total = sum(t.minutes_spent for t in DailyTask.objects.filter(employee=self.emp))
        self.assertEqual(total, 90)
        self.assertEqual(DailyTask.format_minutes(total), "1h 30m")
