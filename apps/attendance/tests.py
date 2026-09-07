"""Rule engine tests - make sure the office policy behaves correctly."""
from datetime import date, datetime, time

from django.test import TestCase

from apps.accounts.models import Shift, User

from datetime import timedelta

from .geo import distance_metres
from .models import (DailyAttendance, OfficeLocation, Outing, PunchLog, PunchPolicy)
from .rules import evaluate_day, required_out_time
from .services import SelfPunchError, rebuild_day, record_punch, self_punch

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


class SelfPunchTests(TestCase):
    """Punching from a browser, with a location attached."""

    @classmethod
    def setUpTestData(cls):
        cls.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), required_hours=9, is_default=True, weekend_days="4,5",
        )
        cls.emp = User.objects.create_user(
            username="kamal", password="pw", employee_id="EMP-020", shift=cls.shift
        )
        # Office at Gulshan 1 circle, 200 m radius.
        cls.office = OfficeLocation.objects.create(
            name="Head office", latitude="23.780600", longitude="90.416500", radius_m=200
        )

    def setUp(self):
        self.policy = PunchPolicy.get_solo()

    def test_distance_calculation(self):
        """Roughly 1 km north of the office should read as about 1 km."""
        d = distance_metres(23.7806, 90.4165, 23.7896, 90.4165)
        self.assertTrue(950 < d < 1050, d)

    def test_punch_inside_office(self):
        log, record, direction = self_punch(
            self.emp, latitude="23.780650", longitude="90.416520", accuracy_m=20
        )
        self.assertEqual(direction, PunchLog.Direction.IN)
        self.assertEqual(log.location_status, PunchLog.LocationStatus.INSIDE)
        self.assertEqual(log.office, self.office)
        self.assertLess(log.distance_m, 50)
        self.assertEqual(log.source, PunchLog.Source.SELF)

    def test_punch_away_from_office_is_flagged_not_blocked(self):
        """Field staff must still be able to punch - it is just marked as away."""
        log, _, _ = self_punch(self.emp, latitude="23.800000", longitude="90.450000", accuracy_m=30)
        self.assertEqual(log.location_status, PunchLog.LocationStatus.OUTSIDE)
        self.assertGreater(log.distance_m, 1000)

    def test_office_only_mode_blocks_remote_punch(self):
        self.policy.allow_outside_office = False
        self.policy.save()
        with self.assertRaises(SelfPunchError):
            self_punch(self.emp, latitude="23.900000", longitude="90.500000", accuracy_m=30)

    def test_location_required_by_default(self):
        with self.assertRaises(SelfPunchError):
            self_punch(self.emp)

    def test_punch_without_location_when_allowed(self):
        self.policy.require_location = False
        self.policy.save()
        log, _, _ = self_punch(self.emp)
        self.assertEqual(log.location_status, PunchLog.LocationStatus.MISSING)

    def test_vague_reading_is_flagged(self):
        self.policy.max_accuracy_m = 100
        self.policy.save()
        log, _, _ = self_punch(
            self.emp, latitude="23.780650", longitude="90.416520", accuracy_m=800
        )
        self.assertEqual(log.location_status, PunchLog.LocationStatus.WEAK)

    def test_punches_alternate_in_and_out(self):
        base = datetime.combine(DAY, time(9, 0))
        directions = []
        for i in range(4):
            _, _, direction = self_punch(
                self.emp, latitude="23.780650", longitude="90.416520", accuracy_m=20,
                when=base + timedelta(hours=i * 2),
            )
            directions.append(direction)
        self.assertEqual(directions, ["IN", "OUT", "IN", "OUT"])

    def test_self_punches_feed_the_normal_day_calculation(self):
        base = datetime.combine(DAY, time(10, 2))
        self_punch(self.emp, latitude="23.780650", longitude="90.416520",
                   accuracy_m=20, when=base)
        self_punch(self.emp, latitude="23.780650", longitude="90.416520",
                   accuracy_m=20, when=datetime.combine(DAY, time(19, 2)))
        rec = DailyAttendance.objects.get(employee=self.emp, date=DAY)
        self.assertEqual(rec.status, S.LATE)
        self.assertEqual(rec.required_out.time(), time(19, 2))

    def test_switching_self_punch_off(self):
        self.policy.self_punch_enabled = False
        self.policy.save()
        with self.assertRaises(SelfPunchError):
            self_punch(self.emp, latitude="23.780650", longitude="90.416520", accuracy_m=20)

    def test_double_submit_is_rejected(self):
        when = datetime.combine(DAY, time(9, 0))
        self_punch(self.emp, latitude="23.780650", longitude="90.416520",
                   accuracy_m=20, when=when)
        with self.assertRaises(SelfPunchError):
            self_punch(self.emp, latitude="23.780650", longitude="90.416520",
                       accuracy_m=20, when=when)

    def test_double_tap_is_explained_not_swallowed(self):
        """Tapping twice in a minute gets a clear message, not a silent drop."""
        when = datetime.combine(DAY, time(9, 0))
        self_punch(self.emp, latitude="23.780650", longitude="90.416520",
                   accuracy_m=20, when=when)
        with self.assertRaises(SelfPunchError) as caught:
            self_punch(self.emp, latitude="23.780650", longitude="90.416520",
                       accuracy_m=20, when=when + timedelta(seconds=30))
        self.assertIn("minutes ago", str(caught.exception))


class PaginationTests(TestCase):
    """Long lists are served a page at a time."""

    @classmethod
    def setUpTestData(cls):
        cls.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), is_default=True, weekend_days="4,5",
        )
        cls.admin = User.objects.create_user(
            username="chief", password="pw", employee_id="EMP-050",
            role=User.Role.ADMIN, shift=cls.shift, is_attendance_tracked=False,
        )
        cls.emp = User.objects.create_user(
            username="worker", password="pw", employee_id="EMP-051", shift=cls.shift
        )
        # 120 punches spread over one day, well past a single page.
        base = datetime.combine(DAY, time(8, 0))
        PunchLog.objects.bulk_create([
            PunchLog(employee=cls.emp, punch_time=base + timedelta(minutes=i * 5),
                     source=PunchLog.Source.MANUAL)
            for i in range(120)
        ])

    def test_punch_log_page_is_capped(self):
        self.client.force_login(self.admin)
        response = self.client.get(f"/attendance/punches/?date={DAY:%Y-%m-%d}")
        page = response.context["page"]
        self.assertEqual(page.paginator.count, 120)
        self.assertEqual(len(page.object_list), 50)
        self.assertTrue(page.has_next())

    def test_second_page_has_the_rest(self):
        self.client.force_login(self.admin)
        response = self.client.get(f"/attendance/punches/?date={DAY:%Y-%m-%d}&page=3")
        self.assertEqual(response.context["page"].number, 3)
        self.assertEqual(len(response.context["page"].object_list), 20)

    def test_out_of_range_page_falls_back_to_the_first(self):
        """A stale bookmark should show data, not a 404."""
        self.client.force_login(self.admin)
        response = self.client.get(f"/attendance/punches/?date={DAY:%Y-%m-%d}&page=999")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page"].number, 1)

    def test_junk_page_number_is_survivable(self):
        self.client.force_login(self.admin)
        response = self.client.get(f"/attendance/punches/?date={DAY:%Y-%m-%d}&page=abc")
        self.assertEqual(response.status_code, 200)

    def test_per_page_is_clamped(self):
        """Nobody can ask for ten thousand rows in one request."""
        self.client.force_login(self.admin)
        response = self.client.get(f"/attendance/punches/?date={DAY:%Y-%m-%d}&per_page=100000")
        self.assertEqual(len(response.context["page"].object_list), 120)
        self.assertEqual(response.context["page"].paginator.per_page, 200)

    def test_filters_survive_paging(self):
        """Totals are for the whole filtered set, not just the page shown."""
        for i in range(60):
            rebuild_day(self.emp, DAY - timedelta(days=i % 30))
        self.client.force_login(self.admin)
        response = self.client.get("/attendance/sheet/?from=2026-01-01&to=2026-12-31&page=2")
        self.assertEqual(response.status_code, 200)
        totals = response.context["totals"]
        page = response.context["page"]
        self.assertEqual(totals["rows"], page.paginator.count)


class CorrectionTests(TestCase):
    """Employees asking for a mis-recorded day to be fixed."""

    @classmethod
    def setUpTestData(cls):
        cls.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), required_hours=9, half_day_hours=4,
            is_default=True, weekend_days="4,5",
        )
        cls.emp = User.objects.create_user(
            username="mainul", password="pw", employee_id="EMP-100", shift=cls.shift)
        cls.admin = User.objects.create_user(
            username="chief2", password="pw", employee_id="EMP-101",
            role=User.Role.ADMIN, shift=cls.shift, is_attendance_tracked=False)

    def a_day_with_no_out_punch(self):
        record_punch(employee=self.emp, punch_time=datetime.combine(DAY, time(9, 5)))
        return DailyAttendance.objects.get(employee=self.emp, date=DAY)

    def test_a_forgotten_out_punch_costs_the_whole_day(self):
        """Why this feature exists at all."""
        record = self.a_day_with_no_out_punch()
        self.assertEqual(record.status, S.MISSING_OUT)
        self.assertEqual(record.worked_minutes, 0)

    def test_approving_a_correction_fixes_the_day(self):
        from .models import AttendanceCorrection
        from .services import apply_correction

        self.a_day_with_no_out_punch()
        correction = AttendanceCorrection.objects.create(
            employee=self.emp, date=DAY, requested_out=time(18, 10),
            reason="FORGOT_OUT", note="Left at ten past six")

        record = apply_correction(correction, by=self.admin, note="Confirmed with the manager")

        self.assertEqual(record.check_out.time(), time(18, 10))
        self.assertEqual(record.status, S.PRESENT)
        self.assertEqual(record.worked_minutes, 545)
        self.assertTrue(record.is_manual_override)

    def test_the_original_times_are_kept(self):
        from .models import AttendanceCorrection
        from .services import apply_correction

        self.a_day_with_no_out_punch()
        correction = AttendanceCorrection.objects.create(
            employee=self.emp, date=DAY, requested_out=time(18, 10),
            reason="FORGOT_OUT", note="x")
        apply_correction(correction, by=self.admin)
        correction.refresh_from_db()

        self.assertEqual(correction.original_in.time(), time(9, 5))
        self.assertIsNone(correction.original_out)
        self.assertEqual(correction.original_status, S.MISSING_OUT)

    def test_a_corrected_day_survives_the_nightly_rebuild(self):
        """Without the override flag the fix would be silently undone."""
        from .models import AttendanceCorrection
        from .services import apply_correction

        self.a_day_with_no_out_punch()
        correction = AttendanceCorrection.objects.create(
            employee=self.emp, date=DAY, requested_out=time(18, 10),
            reason="FORGOT_OUT", note="x")
        apply_correction(correction, by=self.admin)

        rebuild_day(self.emp, DAY)
        record = DailyAttendance.objects.get(employee=self.emp, date=DAY)
        self.assertEqual(record.check_out.time(), time(18, 10))

    def test_a_correction_still_judges_lateness(self):
        """Corrections fix the record, they do not excuse arriving late."""
        from .models import AttendanceCorrection
        from .services import apply_correction

        record_punch(employee=self.emp, punch_time=datetime.combine(DAY, time(10, 30)))
        correction = AttendanceCorrection.objects.create(
            employee=self.emp, date=DAY, requested_out=time(18, 0),
            reason="FORGOT_OUT", note="x")
        record = apply_correction(correction, by=self.admin)

        self.assertTrue(record.is_late)
        self.assertEqual(record.required_out.time(), time(19, 30))
        self.assertTrue(record.is_early_out)

    def test_rejecting_leaves_the_day_alone(self):
        from .models import AttendanceCorrection
        from .services import reject_correction

        record = self.a_day_with_no_out_punch()
        correction = AttendanceCorrection.objects.create(
            employee=self.emp, date=DAY, requested_out=time(23, 0),
            reason="FORGOT_OUT", note="x")
        reject_correction(correction, by=self.admin, note="Office closes at 7")

        record.refresh_from_db()
        self.assertEqual(record.status, S.MISSING_OUT)
        self.assertIsNone(record.check_out)

    def test_every_decision_is_recorded(self):
        from apps.accounts.models import ActivityLog
        from .models import AttendanceCorrection
        from .services import apply_correction

        self.a_day_with_no_out_punch()
        correction = AttendanceCorrection.objects.create(
            employee=self.emp, date=DAY, requested_out=time(18, 10),
            reason="FORGOT_OUT", note="x")
        apply_correction(correction, by=self.admin)

        entry = ActivityLog.objects.filter(action=ActivityLog.Action.CORRECTION_APPROVED).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.target, self.emp)

    def test_only_one_pending_request_per_day(self):
        from django.db import IntegrityError
        from .models import AttendanceCorrection

        AttendanceCorrection.objects.create(
            employee=self.emp, date=DAY, requested_out=time(18, 0), reason="OTHER", note="x")
        with self.assertRaises(IntegrityError):
            AttendanceCorrection.objects.create(
                employee=self.emp, date=DAY, requested_out=time(19, 0), reason="OTHER", note="y")

    def test_employees_cannot_decide_their_own_requests(self):
        from .models import AttendanceCorrection

        correction = AttendanceCorrection.objects.create(
            employee=self.emp, date=DAY, requested_out=time(18, 0), reason="OTHER", note="x")
        self.client.force_login(self.emp)
        response = self.client.post(f"/attendance/corrections/{correction.pk}/approve/")
        self.assertEqual(response.status_code, 403)
        correction.refresh_from_db()
        self.assertEqual(correction.status, "PENDING")

    def test_problem_days_are_surfaced_to_the_employee(self):
        from .services import days_needing_attention

        self.a_day_with_no_out_punch()
        self.assertIn(DAY, [r.date for r in days_needing_attention(self.emp, limit=400)])


class LoginThrottleTests(TestCase):
    """Password guessing has to get slower, without locking anyone out for good."""

    @classmethod
    def setUpTestData(cls):
        cls.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), is_default=True)
        cls.emp = User.objects.create_user(
            username="target", password="RealPass123", employee_id="EMP-110", shift=cls.shift)

    def guess(self, password="wrong"):
        return self.client.post("/accounts/login/",
                                {"username": "target", "password": password}, follow=True)

    def test_repeated_wrong_passwords_get_blocked(self):
        from apps.accounts.throttle import MAX_ATTEMPTS

        for _ in range(MAX_ATTEMPTS):
            self.guess()
        response = self.guess()
        self.assertContains(response, "Too many failed sign-in attempts")

    def test_the_real_password_stops_working_while_locked(self):
        """A lockout that the attacker can walk past is not a lockout."""
        from apps.accounts.throttle import MAX_ATTEMPTS

        for _ in range(MAX_ATTEMPTS):
            self.guess()
        response = self.guess("RealPass123")
        self.assertFalse(response.context["user"].is_authenticated)

    def test_a_correct_password_clears_the_count(self):
        from apps.accounts.throttle import LoginAttempt

        self.guess()
        self.guess()
        self.assertEqual(LoginAttempt.objects.count(), 2)
        response = self.guess("RealPass123")
        self.assertTrue(response.context["user"].is_authenticated)
        self.assertEqual(LoginAttempt.objects.count(), 0)

    def test_a_few_mistakes_are_forgiven(self):
        self.guess()
        self.guess()
        response = self.guess("RealPass123")
        self.assertTrue(response.context["user"].is_authenticated)

    def test_old_attempts_are_pruned(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.accounts.throttle import LoginAttempt, prune

        self.guess()
        LoginAttempt.objects.update(created_at=timezone.now() - timedelta(days=30))
        self.assertEqual(prune(days=7), 1)
