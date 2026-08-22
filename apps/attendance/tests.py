"""Rule engine tests - make sure the office policy behaves correctly."""
from datetime import date, datetime, time

from django.test import TestCase

from apps.accounts.models import Shift, User

from .models import DailyAttendance, Outing, PunchLog
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


class MultiPunchTests(TestCase):
    """Employees who leave and come back several times a day."""

    @classmethod
    def setUpTestData(cls):
        cls.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), required_hours=9, half_day_hours=4,
            weekend_days="4,5", is_default=True,
            duplicate_window_minutes=3, min_outing_minutes=5,
        )
        cls.emp = User.objects.create_user(
            username="tanvir", password="x", employee_id="EMP-009",
            rfid_card_no="7788", shift=cls.shift,
        )

    def punch(self, h, m):
        from .services import record_punch
        record_punch(employee=self.emp, punch_time=datetime.combine(DAY, time(h, m)))

    def day(self):
        return DailyAttendance.objects.get(employee=self.emp, date=DAY)

    def test_four_punches_make_one_trip(self):
        """In 9:00, out 11:00, back 12:00, out 19:00 -> one trip of an hour."""
        for t in [(9, 0), (11, 0), (12, 0), (19, 0)]:
            self.punch(*t)
        rec = self.day()
        self.assertEqual(rec.check_in.time(), time(9, 0))
        self.assertEqual(rec.check_out.time(), time(19, 0))
        self.assertEqual(rec.trip_count, 1)
        self.assertEqual(rec.outside_minutes, 60)
        self.assertEqual(rec.inside_minutes, 540)          # 2h + 7h inside
        self.assertEqual(rec.outings.count(), 1)

    def test_official_trip_counts_as_work(self):
        for t in [(9, 0), (11, 0), (12, 0), (18, 0)]:
            self.punch(*t)
        outing = Outing.objects.get(employee=self.emp)
        outing.purpose = Outing.Purpose.OFFICIAL
        outing.save()
        rebuild_day(self.emp, DAY)
        rec = self.day()
        self.assertEqual(rec.outside_paid_minutes, 60)
        self.assertEqual(rec.worked_minutes, 540)          # 8h inside + 1h official
        self.assertEqual(rec.required_out.time(), time(18, 0))
        self.assertEqual(rec.status, S.PRESENT)

    def test_personal_trip_pushes_required_out(self):
        for t in [(9, 0), (11, 0), (12, 0), (18, 0)]:
            self.punch(*t)
        outing = Outing.objects.get(employee=self.emp)
        outing.purpose = Outing.Purpose.PERSONAL
        outing.save()
        rebuild_day(self.emp, DAY)
        rec = self.day()
        self.assertEqual(rec.outside_unpaid_minutes, 60)
        self.assertEqual(rec.required_out.time(), time(19, 0))   # 6 PM + the hour taken
        self.assertEqual(rec.worked_minutes, 480)
        self.assertTrue(rec.is_early_out)

    def test_many_trips_in_one_day(self):
        """Seven punches: in, out, in, out, in, out, in -> still inside."""
        for t in [(9, 0), (10, 30), (11, 0), (13, 0), (14, 0), (15, 30), (16, 0)]:
            self.punch(*t)
        rec = self.day()
        self.assertEqual(rec.trip_count, 3)
        self.assertEqual(rec.outside_minutes, 30 + 60 + 30)
        self.assertEqual(rec.status, S.MISSING_OUT)        # odd count, no closing out
        self.assertIsNone(rec.check_out)

    def test_duplicate_tap_ignored(self):
        """A second tap two minutes later is the same event, not an exit."""
        for t in [(9, 0), (9, 2), (18, 0)]:
            self.punch(*t)
        rec = self.day()
        self.assertEqual(rec.trip_count, 0)
        self.assertEqual(rec.check_in.time(), time(9, 0))
        self.assertEqual(rec.check_out.time(), time(18, 0))
        self.assertTrue(PunchLog.objects.get(punch_time__hour=9, punch_time__minute=2).is_ignored)

    def test_very_short_gap_is_not_a_trip(self):
        """Stepping out for four minutes is not worth recording as a trip."""
        for t in [(9, 0), (11, 0), (11, 4), (18, 0)]:
            self.punch(*t)
        rec = self.day()
        self.assertEqual(rec.trip_count, 0)
        self.assertEqual(rec.inside_minutes, 540)

    def test_punch_direction_labels(self):
        for t in [(9, 0), (11, 0), (12, 0), (18, 0)]:
            self.punch(*t)
        dirs = list(PunchLog.objects.filter(employee=self.emp)
                    .order_by("punch_time").values_list("direction", flat=True))
        self.assertEqual(dirs, ["IN", "OUT", "IN", "OUT"])

    def test_note_survives_recalculation(self):
        for t in [(9, 0), (11, 0), (12, 0), (18, 0)]:
            self.punch(*t)
        outing = Outing.objects.get(employee=self.emp)
        outing.purpose = Outing.Purpose.OFFICIAL
        outing.destination = "Client office, Gulshan"
        outing.note = "Contract signing"
        outing.save()
        rebuild_day(self.emp, DAY)
        outing.refresh_from_db()
        self.assertEqual(outing.destination, "Client office, Gulshan")
        self.assertEqual(outing.note, "Contract signing")
