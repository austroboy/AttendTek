"""Rule engine tests - make sure the office policy behaves correctly."""
from datetime import date, datetime, time

from django.test import TestCase

from apps.accounts.models import Shift, User

from .models import DailyAttendance
from .rules import evaluate_day, required_out_time
from .services import rebuild_day, record_punch

S = DailyAttendance.Status
DAY = date(2026, 8, 17)  # Monday


class RuleEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), required_hours=9, half_day_hours=4,
            weekend_days="4,5", is_default=True,
        )

    def ev(self, in_h, in_m, out_h=None, out_m=0):
        ci = datetime.combine(DAY, time(in_h, in_m))
        co = datetime.combine(DAY, time(out_h, out_m)) if out_h else None
        return evaluate_day(self.shift, DAY, ci, co)

    def test_on_time_full_day(self):
        e = self.ev(9, 0, 18, 0)
        self.assertEqual(e.status, S.PRESENT)
        self.assertEqual(e.required_out.time(), time(18, 0))
        self.assertEqual(e.worked_minutes, 540)

    def test_late_pushes_required_out(self):
        """An in-punch at 10:02 AM means staying until 7:02 PM."""
        e = self.ev(10, 2, 19, 2)
        self.assertEqual(e.required_out.time(), time(19, 2))
        self.assertTrue(e.is_late)
        self.assertFalse(e.is_early_out)
        self.assertEqual(e.status, S.LATE)
        self.assertEqual(e.worked_minutes, 540)

    def test_late_and_early_out(self):
        """In at 10:02 and out at 6:30 is both late and an early out."""
        e = self.ev(10, 2, 18, 30)
        self.assertEqual(e.status, S.LATE_EARLY)
        self.assertTrue(e.is_late and e.is_early_out)
        self.assertEqual(e.early_out_minutes, 32)
        self.assertEqual(e.shortfall_minutes, 32)

    def test_grace_period_not_late_but_still_nine_hours(self):
        """9:45 AM is before 10 AM so not LATE, but 9 hours are still required -> out 6:45 PM."""
        e = self.ev(9, 45, 18, 0)
        self.assertFalse(e.is_late)
        self.assertEqual(e.required_out.time(), time(18, 45))
        self.assertTrue(e.is_early_out)
        self.assertEqual(e.status, S.EARLY_OUT)

    def test_extend_only_when_late_mode(self):
        """With the shift setting on, arriving within the grace period keeps 6 PM as the out time."""
        self.shift.extend_only_when_late = True
        e = self.ev(9, 45, 18, 0)
        self.assertEqual(e.required_out.time(), time(18, 0))
        self.assertEqual(e.status, S.PRESENT)
        self.shift.extend_only_when_late = False

    def test_early_arrival_keeps_six_pm(self):
        """Arriving at 8:15 still means 6 PM - the 9 hours are complete by then."""
        e = self.ev(8, 15, 18, 0)
        self.assertEqual(e.required_out.time(), time(18, 0))
        self.assertEqual(e.status, S.PRESENT)
        self.assertEqual(e.overtime_minutes, 0)

    def test_overtime(self):
        e = self.ev(9, 0, 19, 30)
        self.assertEqual(e.overtime_minutes, 90)
        self.assertEqual(e.status, S.PRESENT)

    def test_missing_out_punch(self):
        e = self.ev(9, 10)
        self.assertEqual(e.status, S.MISSING_OUT)

    def test_half_day(self):
        e = self.ev(9, 0, 12, 0)
        self.assertEqual(e.status, S.HALF_DAY)

    def test_absent(self):
        e = evaluate_day(self.shift, DAY, None, None)
        self.assertEqual(e.status, S.ABSENT)

    def test_weekend(self):
        friday = date(2026, 8, 21)
        e = evaluate_day(self.shift, friday, None, None)
        self.assertEqual(e.status, S.WEEKEND)

    def test_required_out_helper(self):
        ci = datetime.combine(DAY, time(11, 30))
        self.assertEqual(required_out_time(self.shift, DAY, ci).time(), time(20, 30))


class PunchFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), required_hours=9, is_default=True, weekend_days="4,5",
        )
        cls.emp = User.objects.create_user(
            username="rakib", password="x", employee_id="EMP-001",
            rfid_card_no="0012345678", device_user_id="101", shift=cls.shift,
        )

    def test_card_punch_creates_attendance(self):
        record_punch(punch_time=datetime.combine(DAY, time(10, 2)), card_no="0012345678")
        record_punch(punch_time=datetime.combine(DAY, time(19, 2)), card_no="0012345678")
        rec = DailyAttendance.objects.get(employee=self.emp, date=DAY)
        self.assertEqual(rec.check_in.time(), time(10, 2))
        self.assertEqual(rec.required_out.time(), time(19, 2))
        self.assertEqual(rec.status, S.LATE)
        self.assertEqual(rec.punch_count, 2)

    def test_duplicate_punch_ignored(self):
        t = datetime.combine(DAY, time(9, 5))
        record_punch(punch_time=t, card_no="0012345678")
        _, created = record_punch(punch_time=t, card_no="0012345678")
        self.assertFalse(created)

    def test_double_tap_not_treated_as_out(self):
        record_punch(punch_time=datetime.combine(DAY, time(9, 0)), card_no="0012345678")
        record_punch(punch_time=datetime.combine(DAY, time(9, 1)), card_no="0012345678")
        rec = DailyAttendance.objects.get(employee=self.emp, date=DAY)
        self.assertIsNone(rec.check_out)
        self.assertEqual(rec.status, S.MISSING_OUT)

    def test_unknown_card_is_unmatched(self):
        log, created = record_punch(punch_time=datetime.combine(DAY, time(9, 0)), card_no="9999")
        self.assertTrue(created)
        self.assertFalse(log.is_matched)
        self.assertIsNone(log.employee)
