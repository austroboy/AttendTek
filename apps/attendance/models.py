from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.utils import now as app_now, today as app_today


class Holiday(models.Model):
    date = models.DateField(unique=True)
    title = models.CharField(max_length=120)
    is_optional = models.BooleanField(default=False)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date:%d %b %Y} - {self.title}"


class PunchLog(models.Model):
    """Raw punches coming from the device. DailyAttendance is built from these."""

    class Direction(models.TextChoices):
        IN = "IN", "In"
        OUT = "OUT", "Out"
        UNKNOWN = "UNKNOWN", "Not paired yet"

    class Source(models.TextChoices):
        DEVICE = "DEVICE", "ZKTeco device"
        SELF = "SELF", "Self punch (web)"
        MANUAL = "MANUAL", "Manual entry"
        IMPORT = "IMPORT", "CSV import"
        HOME = "HOME", "Home office"

    class LocationStatus(models.TextChoices):
        INSIDE = "INSIDE", "At the office"
        OUTSIDE = "OUTSIDE", "Away from the office"
        UNKNOWN = "UNKNOWN", "No office set"
        MISSING = "MISSING", "Location not shared"
        WEAK = "WEAK", "Location too vague"

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="punches",
    )
    device = models.ForeignKey(
        "devices.Device", null=True, blank=True, on_delete=models.SET_NULL, related_name="punches"
    )
    punch_time = models.DateTimeField()
    card_no = models.CharField(max_length=32, blank=True)
    device_user_id = models.CharField(max_length=16, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.DEVICE)
    direction = models.CharField(
        max_length=8, choices=Direction.choices, default=Direction.UNKNOWN,
        help_text="Odd punches of the day are IN, even punches are OUT",
    )
    sequence = models.PositiveSmallIntegerField(
        default=0, help_text="Position of this punch within the day, starting at 1"
    )
    is_ignored = models.BooleanField(
        default=False, help_text="A duplicate tap - not counted when pairing the day"
    )
    raw_status = models.SmallIntegerField(default=0)
    is_matched = models.BooleanField(default=True, help_text="Whether the punch was matched to an employee")

    # --- where the punch came from (self punches only) ---
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    accuracy_m = models.PositiveIntegerField(
        null=True, blank=True, help_text="How precise the phone said the reading was, in metres"
    )
    location_status = models.CharField(
        max_length=8, choices=LocationStatus.choices, default=LocationStatus.UNKNOWN
    )
    office = models.ForeignKey(
        "attendance.OfficeLocation", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="punches",
        help_text="Nearest office when the punch was taken",
    )
    distance_m = models.PositiveIntegerField(
        null=True, blank=True, help_text="Distance from that office, in metres"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    note = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-punch_time"]
        indexes = [models.Index(fields=["employee", "punch_time"])]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "punch_time"], name="uniq_punch_per_employee_time"
            )
        ]

    def __str__(self):
        who = self.employee.display_name if self.employee else f"card {self.card_no}"
        return f"{who} @ {self.punch_time:%d %b %I:%M %p}"

    @property
    def day(self):
        return self.punch_time.date()

    @property
    def has_location(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def coordinates(self):
        return f"{self.latitude},{self.longitude}" if self.has_location else ""

    @property
    def map_url(self):
        """A plain OpenStreetMap link - no API key, opens anywhere."""
        if not self.has_location:
            return ""
        return (f"https://www.openstreetmap.org/?mlat={self.latitude}"
                f"&mlon={self.longitude}#map=18/{self.latitude}/{self.longitude}")

    @property
    def distance_display(self):
        if self.distance_m is None:
            return "—"
        if self.distance_m < 1000:
            return f"{self.distance_m} m"
        return f"{self.distance_m / 1000:.1f} km"

    @property
    def location_badge(self):
        return {
            self.LocationStatus.INSIDE: "ok",
            self.LocationStatus.OUTSIDE: "warn",
            self.LocationStatus.UNKNOWN: "muted",
            self.LocationStatus.MISSING: "bad",
            self.LocationStatus.WEAK: "warn",
        }.get(self.location_status, "muted")


class DailyAttendance(models.Model):
    """One employee's final result for one day."""

    class Status(models.TextChoices):
        PRESENT = "PRESENT", "On time"
        LATE = "LATE", "Late"
        EARLY_OUT = "EARLY_OUT", "Early out"
        LATE_EARLY = "LATE_EARLY", "Late + early out"
        HALF_DAY = "HALF_DAY", "Half day"
        MISSING_OUT = "MISSING_OUT", "Out punch missing"
        ABSENT = "ABSENT", "Absent"
        LEAVE = "LEAVE", "On leave"
        HOLIDAY = "HOLIDAY", "Holiday"
        WEEKEND = "WEEKEND", "Weekend"

    class Mode(models.TextChoices):
        OFFICE = "OFFICE", "Office"
        HOME = "HOME", "Home office"
        LEAVE = "LEAVE", "Leave"
        OFF = "OFF", "Off day"

    OK_STATUSES = (Status.PRESENT,)
    PROBLEM_STATUSES = (Status.LATE, Status.EARLY_OUT, Status.LATE_EARLY, Status.HALF_DAY, Status.MISSING_OUT)

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendance_days"
    )
    date = models.DateField()
    shift = models.ForeignKey("accounts.Shift", null=True, blank=True, on_delete=models.SET_NULL)

    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    required_out = models.DateTimeField(
        null=True, blank=True, help_text="When the employee must leave to complete the required hours"
    )

    worked_minutes = models.PositiveIntegerField(default=0)
    inside_minutes = models.PositiveIntegerField(
        default=0, help_text="Time actually inside the office"
    )
    outside_minutes = models.PositiveIntegerField(
        default=0, help_text="Total time spent out of the office during the day"
    )
    outside_paid_minutes = models.PositiveIntegerField(
        default=0, help_text="Of that, time out on office work"
    )
    outside_unpaid_minutes = models.PositiveIntegerField(
        default=0, help_text="Of that, personal time - it pushes the required out time back"
    )
    trip_count = models.PositiveSmallIntegerField(
        default=0, help_text="How many times the employee left and came back"
    )
    late_minutes = models.PositiveIntegerField(default=0)
    early_out_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    shortfall_minutes = models.PositiveIntegerField(default=0, help_text="How far short of the required hours")

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ABSENT)
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.OFFICE)
    is_late = models.BooleanField(default=False)
    is_early_out = models.BooleanField(default=False)
    punch_count = models.PositiveSmallIntegerField(default=0)
    remarks = models.CharField(max_length=200, blank=True)
    is_manual_override = models.BooleanField(
        default=False, help_text="When set, the day is no longer recalculated automatically"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "employee__employee_id"]
        verbose_name_plural = "Daily attendance"
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="uniq_attendance_per_day")
        ]
        indexes = [models.Index(fields=["date", "status"])]

    def __str__(self):
        return f"{self.employee.display_name} - {self.date:%d %b %Y} - {self.get_status_display()}"

    # ---------- display helpers ----------
    @staticmethod
    def as_hm(minutes):
        return f"{minutes // 60}h {minutes % 60:02d}m"

    @property
    def worked_display(self):
        return self.as_hm(self.worked_minutes)

    @property
    def inside_display(self):
        return self.as_hm(self.inside_minutes)

    @property
    def outside_display(self):
        return self.as_hm(self.outside_minutes)

    @property
    def has_unexplained_trip(self):
        return self.outings.filter(purpose=Outing.Purpose.UNSPECIFIED).exists()

    @property
    def shortfall_display(self):
        return f"{self.shortfall_minutes // 60}h {self.shortfall_minutes % 60:02d}m"

    @property
    def is_ok(self):
        return self.status == self.Status.PRESENT

    @property
    def is_off_day(self):
        return self.status in (self.Status.HOLIDAY, self.Status.WEEKEND, self.Status.LEAVE)

    @property
    def badge_class(self):
        return {
            self.Status.PRESENT: "ok",
            self.Status.LATE: "late",
            self.Status.EARLY_OUT: "early",
            self.Status.LATE_EARLY: "bad",
            self.Status.HALF_DAY: "warn",
            self.Status.MISSING_OUT: "warn",
            self.Status.ABSENT: "bad",
            self.Status.LEAVE: "info",
            self.Status.HOLIDAY: "muted",
            self.Status.WEEKEND: "muted",
        }.get(self.status, "muted")

    def timeline(self):
        """Signature widget: percentages used to place the in/out markers on the day tape."""
        shift = self.shift
        if not (shift and self.check_in):
            return None
        from datetime import datetime

        window_start = datetime.combine(self.date, shift.start_time) - timedelta(hours=1)
        window_end = max(
            datetime.combine(self.date, shift.end_time),
            self.required_out or datetime.combine(self.date, shift.end_time),
            self.check_out or datetime.combine(self.date, shift.end_time),
        ) + timedelta(minutes=30)
        span = (window_end - window_start).total_seconds() or 1

        def pct(dt):
            return max(0.0, min(100.0, (dt - window_start).total_seconds() / span * 100))

        out = self.check_out or self.required_out
        return {
            "in_pct": pct(self.check_in),
            "out_pct": pct(out) if out else None,
            "required_pct": pct(self.required_out) if self.required_out else None,
            "scheduled_in_pct": pct(datetime.combine(self.date, shift.start_time)),
            "scheduled_out_pct": pct(datetime.combine(self.date, shift.end_time)),
            "width": (pct(out) - pct(self.check_in)) if out else 0,
        }


class HomeOfficeEntry(models.Model):
    """Employees who are not coming in log a home office day with their in/out time."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Waiting for approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="home_office_entries"
    )
    date = models.DateField(default=app_today)
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(help_text="Why you are working from home")
    work_summary = models.TextField(blank=True)

    # Where the employee was when they started and finished.
    in_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    in_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    in_accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    out_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    out_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    out_accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    is_self_punched = models.BooleanField(
        default=False, help_text="Times came from the punch buttons, not typed in by hand"
    )
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="reviewed_home_office",
    )
    review_note = models.CharField(max_length=200, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name_plural = "Home office entries"
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="uniq_home_office_per_day")
        ]

    def __str__(self):
        return f"{self.employee.display_name} - home office {self.date:%d %b %Y}"

    @property
    def is_running(self):
        return self.check_in and not self.check_out

    @property
    def in_map_url(self):
        if self.in_latitude is None:
            return ""
        return (f"https://www.openstreetmap.org/?mlat={self.in_latitude}"
                f"&mlon={self.in_longitude}#map=18/{self.in_latitude}/{self.in_longitude}")

    @property
    def out_map_url(self):
        if self.out_latitude is None:
            return ""
        return (f"https://www.openstreetmap.org/?mlat={self.out_latitude}"
                f"&mlon={self.out_longitude}#map=18/{self.out_latitude}/{self.out_longitude}")

    @property
    def badge_class(self):
        return {"PENDING": "warn", "APPROVED": "ok", "REJECTED": "bad"}[self.status]


class Outing(models.Model):
    """One trip out of the office and back, built from a pair of punches.

    Employees leave during the day - to a client, the bank, a delivery - and
    tap the reader on the way out and again on the way back. Each of those
    gaps becomes an Outing the employee can label, so the day is not just a
    single in/out but a record of where the time actually went.
    """

    class Purpose(models.TextChoices):
        OFFICIAL = "OFFICIAL", "Official work"
        PERSONAL = "PERSONAL", "Personal"
        BREAK = "BREAK", "Break / meal"
        UNSPECIFIED = "UNSPECIFIED", "Not stated yet"

    # Purposes that still count towards the day's working hours.
    PAID_PURPOSES = (Purpose.OFFICIAL, Purpose.UNSPECIFIED)

    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="outings"
    )
    day = models.ForeignKey(
        DailyAttendance, null=True, blank=True,
        on_delete=models.CASCADE, related_name="outings",
    )
    date = models.DateField()
    left_at = models.DateTimeField()
    returned_at = models.DateTimeField(null=True, blank=True)
    minutes = models.PositiveIntegerField(default=0)

    out_punch = models.ForeignKey(
        PunchLog, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    in_punch = models.ForeignKey(
        PunchLog, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    purpose = models.CharField(
        max_length=12, choices=Purpose.choices, default=Purpose.UNSPECIFIED
    )
    destination = models.CharField(
        max_length=120, blank=True, help_text="Where did you go?"
    )
    note = models.TextField(blank=True, help_text="What was it for?")

    counts_as_work = models.BooleanField(
        default=True, help_text="Whether this time counts towards the working hours"
    )
    is_admin_adjusted = models.BooleanField(
        default=False, help_text="An admin set counts_as_work by hand"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "left_at"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "left_at"], name="uniq_outing_start")
        ]
        indexes = [models.Index(fields=["date", "purpose"])]

    def __str__(self):
        return f"{self.employee.display_name} out at {self.left_at:%d %b %I:%M %p}"

    def save(self, *args, **kwargs):
        if self.returned_at and self.left_at:
            self.minutes = max(0, int((self.returned_at - self.left_at).total_seconds() // 60))
        if not self.is_admin_adjusted:
            self.counts_as_work = self.purpose in self.PAID_PURPOSES
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        """Still out - no return punch yet."""
        return self.returned_at is None

    @property
    def duration_display(self):
        if self.is_open:
            return "still out"
        return f"{self.minutes // 60}h {self.minutes % 60:02d}m" if self.minutes >= 60 else f"{self.minutes}m"

    @property
    def badge_class(self):
        return {
            self.Purpose.OFFICIAL: "ok",
            self.Purpose.PERSONAL: "warn",
            self.Purpose.BREAK: "info",
            self.Purpose.UNSPECIFIED: "muted",
        }[self.purpose]

    @property
    def needs_explanation(self):
        return self.purpose == self.Purpose.UNSPECIFIED


class OfficeLocation(models.Model):
    """A place where being present counts as being at work.

    Coordinates alone say very little - 23.79, 90.41 means nothing to a manager
    reading a report. Storing the office and a radius turns every punch into a
    plain answer: at the office, or 4 km away.
    """

    name = models.CharField(max_length=80, help_text="e.g. Head office, Uttara branch")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    radius_m = models.PositiveIntegerField(
        default=200,
        help_text="How far from this point still counts as being at the office, in metres",
    )
    address = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.latitude}, {self.longitude})"

    @property
    def map_url(self):
        return (f"https://www.openstreetmap.org/?mlat={self.latitude}"
                f"&mlon={self.longitude}#map=17/{self.latitude}/{self.longitude}")


class PunchPolicy(models.Model):
    """One row of settings for punching from a phone or laptop.

    This exists because the card reader is not always available - it breaks, or
    someone is at a client site all day. Self punching fills that gap, but it is
    weaker evidence than a card on a reader, so the rules around it are visible
    and adjustable rather than hidden in the code.
    """

    self_punch_enabled = models.BooleanField(
        default=True, help_text="Let employees punch in and out from the website"
    )
    require_location = models.BooleanField(
        default=True, help_text="Refuse the punch if the browser will not share a location"
    )
    allow_outside_office = models.BooleanField(
        default=True,
        help_text=(
            "Allow punches from away from the office. Leave this on for field staff - "
            "the punch is still marked as away, so nothing is hidden."
        ),
    )
    max_accuracy_m = models.PositiveIntegerField(
        default=500,
        help_text="A reading vaguer than this is flagged. Phones indoors are often 50-100 m.",
    )
    notice = models.CharField(
        max_length=200, blank=True,
        help_text="A line shown to employees on the punch page",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Punch policy"

    def __str__(self):
        return "Self punch policy"

    @classmethod
    def get_solo(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create()
        return obj
