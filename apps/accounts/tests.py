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
