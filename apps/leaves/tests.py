"""Leave balances have to be counted per calendar year, not for all time."""
from datetime import date, time

from django.test import TestCase

from apps.accounts.models import Shift, User

from .models import LeaveRequest, LeaveType
from .services import balance_for, check_request, days_used


class LeaveBalanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), is_default=True,
        )
        cls.emp = User.objects.create_user(
            username="rahat", password="pw", employee_id="EMP-090", shift=cls.shift)
        cls.casual = LeaveType.objects.create(name="Casual Leave", annual_quota=10)
        cls.sick = LeaveType.objects.create(name="Sick Leave", annual_quota=14)

    def approve(self, leave_type, start, end, half=False):
        return LeaveRequest.objects.create(
            employee=self.emp, leave_type=leave_type, start_date=start, end_date=end,
            is_half_day=half, reason="x", status=LeaveRequest.Status.APPROVED)

    def test_last_years_leave_does_not_eat_this_years_quota(self):
        """The bug this fixes: quotas are annual, usage was counted for all time."""
        self.approve(self.casual, date(2025, 3, 3), date(2025, 3, 7))     # 5 days in 2025
        self.approve(self.casual, date(2026, 4, 6), date(2026, 4, 7))     # 2 days in 2026

        self.assertEqual(days_used(self.emp, self.casual, 2025), 5)
        self.assertEqual(days_used(self.emp, self.casual, 2026), 2)

        rows = {r["type"].name: r for r in balance_for(self.emp, 2026)}
        self.assertEqual(rows["Casual Leave"]["left"], 8)

    def test_a_request_across_new_year_is_split(self):
        self.approve(self.casual, date(2025, 12, 30), date(2026, 1, 2))   # 2 days each side
        self.assertEqual(days_used(self.emp, self.casual, 2025), 2)
        self.assertEqual(days_used(self.emp, self.casual, 2026), 2)

    def test_half_day_counts_as_half(self):
        self.approve(self.casual, date(2026, 5, 4), date(2026, 5, 4), half=True)
        self.assertEqual(days_used(self.emp, self.casual, 2026), 0.5)

    def test_pending_and_rejected_requests_do_not_count(self):
        LeaveRequest.objects.create(
            employee=self.emp, leave_type=self.casual, start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5), reason="x", status=LeaveRequest.Status.PENDING)
        LeaveRequest.objects.create(
            employee=self.emp, leave_type=self.casual, start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5), reason="x", status=LeaveRequest.Status.REJECTED)
        self.assertEqual(days_used(self.emp, self.casual, 2026), 0)

    def test_leave_types_are_counted_separately(self):
        self.approve(self.casual, date(2026, 2, 2), date(2026, 2, 4))     # 3 casual
        self.approve(self.sick, date(2026, 2, 10), date(2026, 2, 10))     # 1 sick
        rows = {r["type"].name: r for r in balance_for(self.emp, 2026)}
        self.assertEqual(rows["Casual Leave"]["left"], 7)
        self.assertEqual(rows["Sick Leave"]["left"], 13)

    def test_approver_sees_what_the_request_would_cost(self):
        self.approve(self.casual, date(2026, 3, 2), date(2026, 3, 9))     # 8 of 10 used
        pending = LeaveRequest.objects.create(
            employee=self.emp, leave_type=self.casual, start_date=date(2026, 8, 3),
            end_date=date(2026, 8, 6), reason="x")                        # asking for 4 more

        result = check_request(pending)
        self.assertEqual(result["used"], 8)
        self.assertEqual(result["asked"], 4)
        self.assertTrue(result["exceeds"])
        self.assertEqual(result["over_by"], 2)

    def test_a_request_within_quota_is_not_flagged(self):
        pending = LeaveRequest.objects.create(
            employee=self.emp, leave_type=self.casual, start_date=date(2026, 8, 3),
            end_date=date(2026, 8, 4), reason="x")
        self.assertFalse(check_request(pending)["exceeds"])

    def test_going_over_quota_shows_as_over_not_as_negative_left(self):
        self.approve(self.casual, date(2026, 1, 5), date(2026, 1, 16))    # 12 of a 10 day quota
        row = {r["type"].name: r for r in balance_for(self.emp, 2026)}["Casual Leave"]
        self.assertEqual(row["left"], 0)
        self.assertEqual(row["over"], 2)
        self.assertEqual(row["level"], "bad")
