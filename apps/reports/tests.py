"""Export tests: the downloaded file must match the range and filters on screen."""
from datetime import date, datetime, time, timedelta
from io import BytesIO

from django.test import TestCase

from apps.accounts.models import Department, User
from apps.attendance.models import DailyAttendance


class ExportRangeTests(TestCase):
    """A long date range must export the whole range, not only the current month."""

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name="Dev")
        cls.other = Department.objects.create(name="Sales")
        cls.admin = User.objects.create_user(
            username="boss", password="Boss@12345", role="ADMIN",
            employee_id="E000", first_name="Big", last_name="Boss",
        )
        cls.admin.is_staff = True
        cls.admin.is_superuser = True
        cls.admin.save()

        cls.emp_a = User.objects.create_user(
            username="emp_a", password="Pass@12345", role="EMPLOYEE",
            employee_id="E101", first_name="Emp", last_name="A", department=cls.dept,
        )
        cls.emp_b = User.objects.create_user(
            username="emp_b", password="Pass@12345", role="EMPLOYEE",
            employee_id="E102", first_name="Emp", last_name="B", department=cls.other,
        )

        # One row per employee on the 1st and the 15th of Jan..Nov 2026.
        cls.total = 0
        for month in range(1, 12):
            for day in (1, 15):
                for emp in (cls.emp_a, cls.emp_b):
                    d = date(2026, month, day)
                    DailyAttendance.objects.create(
                        employee=emp, date=d,
                        check_in=datetime.combine(d, time(9, 30)),
                        check_out=datetime.combine(d, time(18, 5)),
                        required_out=datetime.combine(d, time(18, 0)),
                        status=DailyAttendance.Status.PRESENT,
                    )
                    cls.total += 1

        # One clearly late row, for the "issues only" filter.
        late_day = date(2026, 5, 20)
        DailyAttendance.objects.create(
            employee=cls.emp_a, date=late_day,
            check_in=datetime.combine(late_day, time(10, 2)),
            check_out=datetime.combine(late_day, time(19, 2)),
            required_out=datetime.combine(late_day, time(19, 2)),
            is_late=True, late_minutes=62,
            status=DailyAttendance.Status.LATE,
        )
        cls.total += 1

    def setUp(self):
        # Post the real login form; client.login() would skip the form checks.
        self.client.post("/accounts/login/", {"username": "boss", "password": "Boss@12345"})

    def _excel_rows(self, query):
        from openpyxl import load_workbook
        response = self.client.get(f"/reports/export/excel/{query}")
        self.assertEqual(response.status_code, 200)
        ws = load_workbook(BytesIO(response.content)).active
        return ws.max_row - 1, response["Content-Disposition"]

    def _csv_rows(self, query):
        response = self.client.get(f"/reports/export/csv/{query}")
        self.assertEqual(response.status_code, 200)
        return len(response.content.decode().strip().splitlines()) - 1

    def test_long_range_exports_every_month(self):
        rows, disposition = self._excel_rows("?from=2026-01-01&to=2026-11-15")
        self.assertEqual(rows, self.total)
        self.assertIn("2026-01-01_to_2026-11-15", disposition)

    def test_export_matches_the_sheet_total(self):
        page = self.client.get("/attendance/sheet/?from=2026-01-01&to=2026-11-15")
        rows, _ = self._excel_rows("?from=2026-01-01&to=2026-11-15")
        self.assertEqual(rows, page.context["totals"]["rows"])

    def test_single_month_range(self):
        rows, disposition = self._excel_rows("?from=2026-03-01&to=2026-03-31")
        self.assertEqual(rows, 4)
        self.assertIn("2026-03", disposition)

    def test_year_month_still_works(self):
        rows, _ = self._excel_rows("?year=2026&month=3")
        self.assertEqual(rows, 4)

    def test_no_params_falls_back_to_current_month(self):
        rows, _ = self._excel_rows("")
        expected = DailyAttendance.objects.filter(
            date__year=date.today().year, date__month=date.today().month
        ).count()
        self.assertEqual(rows, expected)

    def test_bad_dates_do_not_crash(self):
        rows, _ = self._excel_rows("?from=nonsense&to=")
        self.assertGreaterEqual(rows, 0)

    def test_reversed_range_is_swapped(self):
        rows, _ = self._excel_rows("?from=2026-11-15&to=2026-01-01")
        self.assertEqual(rows, self.total)

    def test_department_filter_is_applied(self):
        rows, _ = self._excel_rows(f"?from=2026-01-01&to=2026-11-15&dept={self.dept.id}")
        self.assertEqual(rows, 23)

    def test_employee_filter_is_applied(self):
        rows, _ = self._excel_rows(f"?from=2026-01-01&to=2026-11-15&employee={self.emp_b.id}")
        self.assertEqual(rows, 22)

    def test_status_filter_is_applied(self):
        rows, _ = self._excel_rows("?from=2026-01-01&to=2026-11-15&status=LATE")
        self.assertEqual(rows, 1)

    def test_problem_filter_is_applied(self):
        rows, _ = self._excel_rows("?from=2026-01-01&to=2026-11-15&status=problem")
        self.assertEqual(rows, 1)

    def test_csv_matches_excel(self):
        excel_rows, _ = self._excel_rows("?from=2026-01-01&to=2026-11-15")
        self.assertEqual(self._csv_rows("?from=2026-01-01&to=2026-11-15"), excel_rows)

    def test_sheet_export_button_carries_the_filters(self):
        response = self.client.get("/attendance/sheet/?from=2026-01-01&to=2026-11-15")
        html = response.content.decode()
        self.assertIn("export/excel/?from=2026-01-01&amp;to=2026-11-15", html)
        self.assertIn("export/csv/?from=2026-01-01&amp;to=2026-11-15", html)

    def test_export_shows_where_the_punch_came_from(self):
        from openpyxl import load_workbook

        from apps.attendance.models import OfficeLocation, PunchLog

        office = OfficeLocation.objects.create(
            name="TalenTracker Limited", latitude="23.816148", longitude="90.366637",
            radius_m=100,
        )
        day = date(2026, 6, 10)
        DailyAttendance.objects.create(
            employee=self.emp_a, date=day,
            check_in=datetime.combine(day, time(9, 27)),
            check_out=datetime.combine(day, time(18, 30)),
            required_out=datetime.combine(day, time(18, 0)),
            status=DailyAttendance.Status.PRESENT,
        )
        PunchLog.objects.create(
            employee=self.emp_a, punch_time=datetime.combine(day, time(9, 27)),
            direction=PunchLog.Direction.IN, sequence=1, source=PunchLog.Source.SELF,
            latitude="23.816200", longitude="90.366700", accuracy_m=21,
            office=office, distance_m=25,
            location_status=PunchLog.LocationStatus.INSIDE,
        )
        PunchLog.objects.create(
            employee=self.emp_a, punch_time=datetime.combine(day, time(18, 30)),
            direction=PunchLog.Direction.OUT, sequence=2, source=PunchLog.Source.SELF,
            latitude="23.860000", longitude="90.400000", accuracy_m=20,
            office=office, distance_m=5000,
            location_status=PunchLog.LocationStatus.OUTSIDE,
        )

        response = self.client.get(
            f"/reports/export/excel/?from=2026-06-10&to=2026-06-10&employee={self.emp_a.id}"
        )
        ws = load_workbook(BytesIO(response.content)).active
        header = [c.value for c in ws[1]]
        row = {header[i]: c.value for i, c in enumerate(ws[2])}

        self.assertIn("At the office", row["In - where"])
        self.assertIn("25 m from TalenTracker Limited", row["In - where"])
        self.assertEqual(row["In - distance (m)"], 25)
        self.assertIn("Away from the office", row["Out - where"])
        self.assertIn("5.0 km from TalenTracker Limited", row["Out - where"])
        self.assertEqual(row["Out - distance (m)"], 5000)

    def test_sheet_shows_where_the_punch_came_from(self):
        from apps.attendance.models import OfficeLocation, PunchLog

        office = OfficeLocation.objects.create(
            name="TalenTracker Limited", latitude="23.816148", longitude="90.366637",
            radius_m=100,
        )
        day = date(2026, 7, 8)
        DailyAttendance.objects.create(
            employee=self.emp_a, date=day,
            check_in=datetime.combine(day, time(9, 45)),
            required_out=datetime.combine(day, time(18, 0)),
            status=DailyAttendance.Status.PRESENT,
        )
        PunchLog.objects.create(
            employee=self.emp_a, punch_time=datetime.combine(day, time(9, 45)),
            direction=PunchLog.Direction.IN, sequence=1, source=PunchLog.Source.SELF,
            latitude="23.860000", longitude="90.400000", accuracy_m=20,
            office=office, distance_m=5000,
            location_status=PunchLog.LocationStatus.OUTSIDE,
        )
        html = self.client.get("/attendance/sheet/?from=2026-07-08&to=2026-07-08").content.decode()
        self.assertIn("Away from the office", html)
        self.assertIn("5.0 km from TalenTracker Limited", html)

    def test_locations_do_not_add_a_query_per_row(self):
        """50 rows on screen must not mean 50 extra queries."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/attendance/sheet/?from=2026-01-01&to=2026-11-15")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["records"]), 45)
        self.assertLess(len(ctx.captured_queries), 30)

    def test_employee_cannot_export(self):
        self.client.get("/accounts/logout/")
        self.client.post("/accounts/login/", {"username": "emp_a", "password": "Pass@12345"})
        response = self.client.get("/reports/export/excel/?from=2026-01-01&to=2026-11-15")
        self.assertNotEqual(response.status_code, 200)
