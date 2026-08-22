from datetime import date, datetime, time, timedelta

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.exceptions import ValidationError
from django.db import models


class Department(models.Model):
    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Designation(models.Model):
    title = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class Shift(models.Model):
    """Office timing rules. Each employee can be put on a different shift."""

    name = models.CharField(max_length=60, unique=True)
    start_time = models.TimeField(default=time(9, 0), help_text="Office start (9:00 AM)")
    end_time = models.TimeField(default=time(18, 0), help_text="Office end (6:00 PM)")
    late_after = models.TimeField(
        default=time(10, 0),
        help_text="A punch after this time counts as LATE. Default 10:00 AM",
    )
    required_hours = models.DecimalField(
        max_digits=4, decimal_places=2, default=9,
        help_text="Hours that must be completed each day (default 9)",
    )
    half_day_hours = models.DecimalField(
        max_digits=4, decimal_places=2, default=4,
        help_text="Anything below this counts as a half day",
    )
    extend_only_when_late = models.BooleanField(
        default=False,
        help_text=(
            "Off (default): the required hours are always counted from the in-time. "
            "On: the required out time is only pushed back when the employee is late."
        ),
    )
    duplicate_window_minutes = models.PositiveIntegerField(
        default=3,
        help_text=(
            "Two punches this close together are the same tap read twice, "
            "so the second one is ignored."
        ),
    )
    min_outing_minutes = models.PositiveIntegerField(
        default=5,
        help_text=(
            "A trip out of the office shorter than this is ignored - it is "
            "usually someone tapping the reader twice by mistake."
        ),
    )
    min_out_gap_minutes = models.PositiveIntegerField(
        default=60,
        help_text="No longer used - kept so old data is not lost.",
    )
    weekend_days = models.CharField(
        max_length=20, default="4,5",
        help_text="Weekly holidays: 0=Mon ... 6=Sun. Friday+Saturday = 4,5",
    )
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.start_time:%I:%M %p} - {self.end_time:%I:%M %p})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Shift.objects.exclude(pk=self.pk).update(is_default=False)

    @property
    def weekend_list(self):
        return [int(x) for x in self.weekend_days.split(",") if x.strip().isdigit()]

    def is_weekend(self, day: date) -> bool:
        return day.weekday() in self.weekend_list

    @property
    def required_delta(self) -> timedelta:
        return timedelta(hours=float(self.required_hours))

    @property
    def half_day_delta(self) -> timedelta:
        return timedelta(hours=float(self.half_day_hours))

    def scheduled_in(self, day: date) -> datetime:
        return datetime.combine(day, self.start_time)

    def scheduled_out(self, day: date) -> datetime:
        return datetime.combine(day, self.end_time)

    @classmethod
    def get_default(cls):
        return cls.objects.filter(is_default=True).first() or cls.objects.first()


class UserQuerySet(models.QuerySet):
    def employees(self):
        return self.filter(is_active=True).exclude(role=User.Role.ADMIN)

    def active_staff(self):
        return self.filter(is_active=True, is_attendance_tracked=True)


class UserManager(DjangoUserManager.from_queryset(UserQuerySet)):
    """Django's create_user/createsuperuser plus our custom queryset."""


class User(AbstractUser):
    """Custom user = one employee. The RFID card ID is stored here."""

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        HR = "HR", "HR / Manager"
        EMPLOYEE = "EMPLOYEE", "Employee"

    class WorkPolicy(models.TextChoices):
        OFFICE = "OFFICE", "Office only"
        HYBRID = "HYBRID", "Office + Home office"
        REMOTE = "REMOTE", "Remote only"

    employee_id = models.CharField(max_length=20, unique=True, help_text="Company employee code, e.g. EMP-001")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.EMPLOYEE)

    # --- RFID / device mapping ---
    rfid_card_no = models.CharField(
        max_length=32, unique=True, null=True, blank=True,
        verbose_name="RFID card ID",
        help_text="The number printed on the card, or read from the device",
    )
    device_user_id = models.CharField(
        max_length=16, null=True, blank=True, unique=True,
        help_text="User ID stored inside the ZKTeco F18",
    )
    card_issued_on = models.DateField(null=True, blank=True)

    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="members")
    designation = models.ForeignKey(Designation, null=True, blank=True, on_delete=models.SET_NULL, related_name="members")
    shift = models.ForeignKey(Shift, null=True, blank=True, on_delete=models.SET_NULL, related_name="members")
    manager = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="team")

    phone = models.CharField(max_length=20, blank=True)
    joining_date = models.DateField(null=True, blank=True)
    photo = models.ImageField(upload_to="employees/", null=True, blank=True)
    work_policy = models.CharField(max_length=10, choices=WorkPolicy.choices, default=WorkPolicy.OFFICE)
    is_attendance_tracked = models.BooleanField(default=True)

    objects = UserManager()

    class Meta:
        ordering = ["employee_id"]

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.employee_id})"

    def clean(self):
        if self.rfid_card_no:
            self.rfid_card_no = self.rfid_card_no.strip()
            if not self.rfid_card_no.isalnum():
                raise ValidationError({"rfid_card_no": "Card ID may only contain letters and numbers."})

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        parts = (self.get_full_name() or self.username).split()
        return "".join(p[0].upper() for p in parts[:2]) or "?"

    @property
    def is_manager(self):
        return self.role in (self.Role.ADMIN, self.Role.HR) or self.is_superuser

    @property
    def can_home_office(self):
        return self.work_policy in (self.WorkPolicy.HYBRID, self.WorkPolicy.REMOTE)

    @property
    def effective_shift(self):
        return self.shift or Shift.get_default()
