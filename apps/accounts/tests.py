"""The employee's own profile page: what they may change, and what they may not."""
import io
from datetime import date, time

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import Department, Shift

User = get_user_model()


def a_png(size_px=8):
    """A tiny real PNG, so Pillow accepts it as an image."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (size_px, size_px), (27, 127, 196)).save(buffer, format="PNG")
    return SimpleUploadedFile("me.png", buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT="/tmp/attendtek-test-media")
class ProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), is_default=True,
        )
        cls.dept = Department.objects.create(name="Engineering")
        cls.emp = User.objects.create_user(
            username="ashfaq", password="StartPass123", employee_id="EMP-060",
            first_name="Ashfaqur", last_name="Rahman", department=cls.dept,
            shift=cls.shift, joining_date=date(2024, 3, 1), rfid_card_no="55501",
        )

    def setUp(self):
        self.client.force_login(self.emp)

    def test_profile_page_loads(self):
        response = self.client.get("/accounts/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ashfaqur Rahman")
        self.assertContains(response, "EMP-060")

    def test_employee_can_update_their_own_details(self):
        self.client.post("/accounts/profile/", {
            "form": "profile", "first_name": "Ashfaqur", "last_name": "Rahman",
            "email": "ashfaq@example.com", "phone": "01711223344",
        }, follow=True)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.email, "ashfaq@example.com")
        self.assertEqual(self.emp.phone, "01711223344")

    def test_photo_upload(self):
        self.client.post("/accounts/profile/", {
            "form": "profile", "first_name": "Ashfaqur", "last_name": "Rahman",
            "email": "a@example.com", "phone": "", "photo": a_png(),
        }, follow=True)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.photo)
        self.assertIn("employees/", self.emp.photo.name)

    def test_oversized_photo_is_refused(self):
        """The size rule fires on a real image that is simply too big."""
        from .forms import ProfileForm

        photo = a_png()
        photo.size = 6 * 1024 * 1024          # a valid image, pretending to be 6 MB
        form = ProfileForm(
            {"first_name": "Ashfaqur", "last_name": "Rahman", "email": "a@example.com",
             "phone": ""},
            {"photo": photo}, instance=self.emp,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("over 5 MB", str(form.errors["photo"]))

    def test_a_file_that_is_not_an_image_is_refused(self):
        junk = SimpleUploadedFile("notes.txt", b"just some text", content_type="text/plain")
        response = self.client.post("/accounts/profile/", {
            "form": "profile", "first_name": "Ashfaqur", "last_name": "Rahman",
            "email": "a@example.com", "phone": "", "photo": junk,
        })
        self.assertContains(response, "valid image")
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.photo)

    def test_password_change_keeps_the_person_signed_in(self):
        response = self.client.post("/accounts/profile/", {
            "form": "password", "old_password": "StartPass123",
            "new_password1": "BrandNewPass456", "new_password2": "BrandNewPass456",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password("BrandNewPass456"))
        # Still signed in - the session was refreshed rather than dropped.
        self.assertEqual(self.client.get("/accounts/profile/").status_code, 200)

    def test_wrong_current_password_is_rejected(self):
        self.client.post("/accounts/profile/", {
            "form": "password", "old_password": "NotMyPassword",
            "new_password1": "BrandNewPass456", "new_password2": "BrandNewPass456",
        })
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.check_password("StartPass123"))

    def test_employee_cannot_change_their_own_pay_relevant_fields(self):
        """Employee ID, card and shift stay with the admin - posting them does nothing."""
        self.client.post("/accounts/profile/", {
            "form": "profile", "first_name": "Ashfaqur", "last_name": "Rahman",
            "email": "a@example.com", "phone": "",
            "employee_id": "EMP-999", "rfid_card_no": "99999",
            "role": "ADMIN", "shift": "",
        }, follow=True)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.employee_id, "EMP-060")
        self.assertEqual(self.emp.rfid_card_no, "55501")
        self.assertEqual(self.emp.role, User.Role.EMPLOYEE)

    def test_initials_used_when_there_is_no_photo(self):
        self.assertEqual(self.emp.initials, "AR")

    def test_signed_out_visitors_are_sent_to_login(self):
        self.client.logout()
        response = self.client.get("/accounts/profile/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_photo_can_be_removed(self):
        """The 'remove my photo' checkbox puts the initials back."""
        self.client.post("/accounts/profile/", {
            "form": "profile", "first_name": "Ashfaqur", "last_name": "Rahman",
            "email": "a@example.com", "phone": "", "photo": a_png(),
        }, follow=True)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.photo)

        self.client.post("/accounts/profile/", {
            "form": "profile", "first_name": "Ashfaqur", "last_name": "Rahman",
            "email": "a@example.com", "phone": "", "remove_photo": "on",
        }, follow=True)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.photo)

    def test_saving_other_details_keeps_the_existing_photo(self):
        """A plain save must not wipe the picture just because no file was picked."""
        self.client.post("/accounts/profile/", {
            "form": "profile", "first_name": "Ashfaqur", "last_name": "Rahman",
            "email": "a@example.com", "phone": "", "photo": a_png(),
        }, follow=True)
        self.emp.refresh_from_db()
        original = self.emp.photo.name

        self.client.post("/accounts/profile/", {
            "form": "profile", "first_name": "Ashfaqur", "last_name": "Rahman",
            "email": "changed@example.com", "phone": "01755556666",
        }, follow=True)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.photo.name, original)
        self.assertEqual(self.emp.email, "changed@example.com")

    def test_sidebar_links_to_the_profile(self):
        response = self.client.get("/attendance/me/")
        self.assertContains(response, 'href="/accounts/profile/"')
        self.assertContains(response, "me-card")


class OffboardingTests(TestCase):
    """Someone leaving must lose access without losing their history."""

    def setUp(self):
        self.shift = Shift.objects.create(
            name="General", start_time=time(9, 0), end_time=time(18, 0),
            late_after=time(10, 0), is_default=True, weekend_days="4,5",
        )
        self.admin = User.objects.create_user(
            username="hrhead", password="pw", employee_id="EMP-080",
            role=User.Role.ADMIN, shift=self.shift, is_attendance_tracked=False,
        )
        self.emp = User.objects.create_user(
            username="leaver", password="LeavePass123", employee_id="EMP-081",
            first_name="Sumaiya", last_name="Rahman", shift=self.shift,
            rfid_card_no="70001", joining_date=date(2025, 1, 6),
        )

    # ---------- the service ----------
    def sign_in(self, username="leaver", password="LeavePass123"):
        """Go through the real login page, the way a person would."""
        return self.client.post("/accounts/login/",
                                {"username": username, "password": password}, follow=True)

    def test_deactivation_blocks_login(self):
        from .offboarding import deactivate_employee

        response = self.sign_in()
        self.assertTrue(response.context["user"].is_authenticated)
        self.client.logout()

        deactivate_employee(self.emp, by=self.admin, exit_date=date(2026, 8, 31),
                            reason="RESIGNED")
        response = self.sign_in()
        self.assertFalse(response.context["user"].is_authenticated)

    def test_a_deactivated_account_cannot_reach_any_page(self):
        """Belt and braces: even a session made another way is stopped."""
        from .offboarding import deactivate_employee

        self.client.force_login(self.emp)
        deactivate_employee(self.emp, by=self.admin, exit_date=date(2026, 8, 31))
        self.emp.refresh_from_db()

        self.client.force_login(self.emp)          # as if a session survived
        response = self.client.get("/attendance/me/", follow=True)
        self.assertIn("/accounts/login/", response.redirect_chain[-1][0])

    def test_open_session_is_ended_immediately(self):
        """The real gap: Django keeps an existing session alive on its own."""
        from .offboarding import deactivate_employee

        self.client.login(username="leaver", password="LeavePass123")
        self.assertEqual(self.client.get("/attendance/me/").status_code, 200)

        deactivate_employee(self.emp, by=self.admin, exit_date=date(2026, 8, 31))

        response = self.client.get("/attendance/me/", follow=True)
        self.assertIn("/accounts/login/", response.redirect_chain[-1][0])

    def test_history_is_kept(self):
        from apps.attendance.models import DailyAttendance
        from apps.tasks.models import DailyTask
        from .offboarding import deactivate_employee

        DailyAttendance.objects.create(employee=self.emp, date=date(2026, 8, 20),
                                       shift=self.shift, status="PRESENT")
        DailyTask.objects.create(employee=self.emp, date=date(2026, 8, 20),
                                 title="Handover", minutes_spent=120)

        deactivate_employee(self.emp, by=self.admin, exit_date=date(2026, 8, 31))

        self.assertTrue(DailyAttendance.objects.filter(employee=self.emp).exists())
        self.assertTrue(DailyTask.objects.filter(employee=self.emp).exists())
        self.assertTrue(User.objects.filter(pk=self.emp.pk).exists())

    def test_no_absences_pile_up_after_the_last_working_day(self):
        from apps.attendance.models import DailyAttendance
        from apps.attendance.services import mark_absentees
        from .offboarding import deactivate_employee

        deactivate_employee(self.emp, by=self.admin, exit_date=date(2026, 8, 31))
        mark_absentees(date(2026, 9, 7))          # a Monday after they left
        self.assertFalse(
            DailyAttendance.objects.filter(employee=self.emp, date=date(2026, 9, 7)).exists())

    def test_future_empty_days_are_cleared_on_exit(self):
        from apps.attendance.models import DailyAttendance
        from .offboarding import deactivate_employee

        DailyAttendance.objects.create(employee=self.emp, date=date(2026, 9, 10),
                                       shift=self.shift, status="ABSENT")
        deactivate_employee(self.emp, by=self.admin, exit_date=date(2026, 8, 31))
        self.assertFalse(
            DailyAttendance.objects.filter(employee=self.emp, date=date(2026, 9, 10)).exists())

    def test_a_day_with_a_real_punch_after_the_exit_date_is_left_alone(self):
        """Never quietly delete evidence that somebody was actually there."""
        from datetime import datetime
        from apps.attendance.models import DailyAttendance
        from .offboarding import deactivate_employee

        DailyAttendance.objects.create(
            employee=self.emp, date=date(2026, 9, 2), shift=self.shift,
            check_in=datetime(2026, 9, 2, 9, 5), status="PRESENT")
        deactivate_employee(self.emp, by=self.admin, exit_date=date(2026, 8, 31))
        self.assertTrue(
            DailyAttendance.objects.filter(employee=self.emp, date=date(2026, 9, 2)).exists())

    def test_pending_requests_are_cancelled(self):
        from apps.leaves.models import LeaveRequest, LeaveType
        from .offboarding import deactivate_employee

        leave_type = LeaveType.objects.create(name="Casual Leave", annual_quota=10)
        request = LeaveRequest.objects.create(
            employee=self.emp, leave_type=leave_type, start_date=date(2026, 9, 10),
            end_date=date(2026, 9, 11), reason="Trip")

        deactivate_employee(self.emp, by=self.admin, exit_date=date(2026, 8, 31))
        request.refresh_from_db()
        self.assertEqual(request.status, LeaveRequest.Status.CANCELLED)

    def test_they_drop_out_of_active_staff(self):
        from .offboarding import deactivate_employee

        self.assertIn(self.emp, User.objects.active_staff())
        deactivate_employee(self.emp, by=self.admin, exit_date=date(2026, 8, 31))
        self.assertNotIn(self.emp, User.objects.active_staff())
        self.assertIn(self.emp, User.objects.former())

    def test_counts_on_respects_both_ends_of_employment(self):
        self.emp.exit_date = date(2026, 8, 31)
        self.assertFalse(self.emp.counts_on(date(2024, 12, 1)))   # before joining
        self.assertTrue(self.emp.counts_on(date(2026, 8, 20)))
        self.assertFalse(self.emp.counts_on(date(2026, 9, 1)))    # after leaving

    def test_reactivation_restores_access(self):
        from .offboarding import deactivate_employee, reactivate_employee

        deactivate_employee(self.emp, by=self.admin, exit_date=date(2026, 8, 31))
        reactivate_employee(self.emp, by=self.admin)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.is_active)
        self.assertIsNone(self.emp.exit_date)
        response = self.sign_in()
        self.assertTrue(response.context["user"].is_authenticated)

    # ---------- the screens ----------
    def test_admin_can_deactivate_from_the_page(self):
        self.client.force_login(self.admin)
        response = self.client.post(f"/accounts/employees/{self.emp.pk}/deactivate/", {
            "exit_date": "2026-08-31", "reason": "RESIGNED",
            "note": "Moved abroad", "cancel_pending": "on", "confirm": "on",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.is_active)
        self.assertEqual(self.emp.exit_reason, "RESIGNED")
        self.assertEqual(self.emp.deactivated_by, self.admin)

    def test_the_confirm_box_is_required(self):
        self.client.force_login(self.admin)
        self.client.post(f"/accounts/employees/{self.emp.pk}/deactivate/", {
            "exit_date": "2026-08-31", "reason": "RESIGNED", "note": "",
        })
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.is_active)

    def test_an_admin_cannot_deactivate_themselves(self):
        self.client.force_login(self.admin)
        self.client.post(f"/accounts/employees/{self.admin.pk}/deactivate/", {
            "exit_date": "2026-08-31", "reason": "OTHER", "confirm": "on",
        }, follow=True)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_an_employee_cannot_deactivate_anybody(self):
        self.client.force_login(self.emp)
        response = self.client.get(f"/accounts/employees/{self.admin.pk}/deactivate/")
        self.assertEqual(response.status_code, 403)

    def test_deactivated_login_says_why(self):
        from .offboarding import deactivate_employee

        deactivate_employee(self.emp, by=self.admin, exit_date=date(2026, 8, 31))
        response = self.client.post("/accounts/login/",
                                    {"username": "leaver", "password": "LeavePass123"})
        self.assertContains(response, "deactivated")
