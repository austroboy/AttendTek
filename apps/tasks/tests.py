"""Task logging - the length of a task is kept in whole minutes."""
from datetime import date, time

from django.test import TestCase

from apps.accounts.models import Shift, User

from .forms import DailyTaskForm
from .models import DailyTask
from .services import (coverage, employee_rows, period_bounds, shift_period,
                       summarise)


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


class TaskReportTests(TestCase):
    """Day, week and month roll-ups of the task log."""

    @classmethod
    def setUpTestData(cls):
        cls.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), is_default=True, weekend_days="4,5",
        )
        cls.emp = User.objects.create_user(
            username="sadia", password="pw", employee_id="EMP-031", shift=cls.shift
        )
        # Monday 24 Aug 2026 through Wednesday 26 Aug.
        for day, minutes, project in [
            (date(2026, 8, 24), 65, "Client-A"),
            (date(2026, 8, 24), 25, "Internal"),
            (date(2026, 8, 25), 480, "Client-A"),
            (date(2026, 8, 26), 120, ""),
        ]:
            DailyTask.objects.create(
                employee=cls.emp, date=day, title="Work", project=project,
                minutes_spent=minutes, progress="DONE",
            )

    def test_day_bounds(self):
        start, end, label = period_bounds("day", date(2026, 8, 26))
        self.assertEqual((start, end), (date(2026, 8, 26), date(2026, 8, 26)))
        self.assertIn("Wednesday", label)

    def test_week_runs_monday_to_sunday(self):
        start, end, _ = period_bounds("week", date(2026, 8, 26))
        self.assertEqual(start, date(2026, 8, 24))
        self.assertEqual(end, date(2026, 8, 30))

    def test_month_bounds(self):
        start, end, label = period_bounds("month", date(2026, 8, 15))
        self.assertEqual((start, end), (date(2026, 8, 1), date(2026, 8, 31)))
        self.assertEqual(label, "August 2026")

    def test_previous_and_next_month(self):
        self.assertEqual(shift_period("month", date(2026, 1, 31), -1).month, 12)
        self.assertEqual(shift_period("month", date(2026, 12, 15), 1).year, 2027)

    def test_daily_total(self):
        start, end, _ = period_bounds("day", date(2026, 8, 24))
        summary = summarise(
            DailyTask.objects.filter(employee=self.emp, date__range=(start, end)), start, end)
        self.assertEqual(summary["total_minutes"], 90)
        self.assertEqual(summary["total_display"], "1h 30m")

    def test_weekly_totals_and_projects(self):
        start, end, _ = period_bounds("week", date(2026, 8, 26))
        summary = summarise(
            DailyTask.objects.filter(employee=self.emp, date__range=(start, end)), start, end)
        self.assertEqual(summary["total_minutes"], 690)
        self.assertEqual(summary["total_display"], "11h 30m")
        self.assertEqual(summary["logged_days"], 3)
        self.assertEqual(len(summary["days"]), 7)
        self.assertEqual(summary["projects"][0]["name"], "Client-A")
        self.assertEqual(summary["projects"][0]["minutes"], 545)
        # A task with no project should not vanish from the breakdown.
        self.assertIn("Unassigned", [p["name"] for p in summary["projects"]])

    def test_coverage_against_time_at_work(self):
        result = coverage(logged=270, worked=540)
        self.assertEqual(result["percent"], 50)
        self.assertEqual(result["gap_display"], "4h 30m")
        self.assertEqual(result["level"], "warn")

    def test_coverage_without_attendance_does_not_divide_by_zero(self):
        self.assertEqual(coverage(logged=60, worked=0)["percent"], 0)

    def test_employee_row_includes_people_who_logged_nothing(self):
        quiet = User.objects.create_user(
            username="quiet", password="pw", employee_id="EMP-032", shift=self.shift)
        start, end, _ = period_bounds("week", date(2026, 8, 26))
        rows = employee_rows([self.emp, quiet], start, end)
        by_name = {r["employee"].username: r for r in rows}
        self.assertEqual(by_name["quiet"]["minutes"], 0)
        self.assertEqual(by_name["sadia"]["minutes"], 690)
        self.assertEqual(rows[0]["employee"].username, "sadia")   # sorted by time logged
