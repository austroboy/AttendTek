"""Demo data for exploring the project.  python manage.py seed_demo"""
import random
from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.utils import now as app_now, today as app_today

from apps.accounts.models import Department, Designation, Shift, User
from apps.attendance.models import Holiday, HomeOfficeEntry, PunchLog
from apps.attendance.services import rebuild_range, record_punch
from apps.leaves.models import LeaveRequest, LeaveType
from apps.tasks.models import DailyTask

NAMES = [
    ("Rakib", "Hasan", "Engineering"), ("Nusrat", "Jahan", "Engineering"),
    ("Tanvir", "Ahmed", "Engineering"), ("Sadia", "Islam", "Design"),
    ("Mehedi", "Hasan", "Design"), ("Farhana", "Akter", "Accounts"),
    ("Imran", "Kabir", "Sales"), ("Sumaiya", "Rahman", "Sales"),
    ("Arif", "Chowdhury", "HR"), ("Nabila", "Sultana", "Support"),
]
TASKS = [
    "Login API integration", "Client dashboard UI", "Bug fix - invoice pdf",
    "Monthly report prepare", "Client meeting follow up", "Database backup script",
    "Landing page design", "Payroll sheet update", "Support ticket clear",
]


class Command(BaseCommand):
    help = "Creates demo employees, punches, leave requests and tasks."

    def handle(self, *args, **options):
        shift, _ = Shift.objects.get_or_create(
            name="General (9 AM - 6 PM)",
            defaults=dict(start_time=time(9, 0), end_time=time(18, 0),
                          late_after=time(10, 0), required_hours=9,
                          half_day_hours=4, weekend_days="4,5", is_default=True),
        )
        for name in ["Casual Leave", "Sick Leave", "Annual Leave"]:
            LeaveType.objects.get_or_create(name=name, defaults={"annual_quota": 10})

        admin, created = User.objects.get_or_create(
            username="admin",
            defaults=dict(employee_id="EMP-000", first_name="Office", last_name="Admin",
                          role=User.Role.ADMIN, is_staff=True, is_superuser=True,
                          shift=shift, is_attendance_tracked=False,
                          joining_date=date(2022, 1, 1)),
        )
        if created:
            admin.set_password("admin123")
            admin.save()

        employees = []
        for i, (first, last, dept_name) in enumerate(NAMES, start=1):
            dept, _ = Department.objects.get_or_create(name=dept_name)
            desig, _ = Designation.objects.get_or_create(title="Executive" if i % 3 else "Senior Executive")
            emp, made = User.objects.get_or_create(
                username=f"{first.lower()}{i}",
                defaults=dict(
                    employee_id=f"EMP-{i:03d}", first_name=first, last_name=last,
                    email=f"{first.lower()}@example.com", phone=f"01{random.randint(300000000, 999999999)}",
                    department=dept, designation=desig, shift=shift,
                    rfid_card_no=f"{1000000 + i * 7331}", device_user_id=str(100 + i),
                    card_issued_on=date(2024, 1, 10), joining_date=date(2023, 6, 1),
                    work_policy=User.WorkPolicy.HYBRID if i % 3 == 0 else User.WorkPolicy.OFFICE,
                ),
            )
            if made:
                emp.set_password("pass1234")
                emp.save()
            employees.append(emp)

        today = app_today()
        start = today - timedelta(days=20)
        PunchLog.objects.all().delete()

        day = start
        while day <= today:
            if not shift.is_weekend(day):
                for emp in employees:
                    roll = random.random()
                    if roll < 0.06:
                        continue  # absent
                    if roll < 0.16 and emp.can_home_office:
                        entry, _ = HomeOfficeEntry.objects.get_or_create(
                            employee=emp, date=day,
                            defaults=dict(
                                reason="Client work from home",
                                check_in=datetime.combine(day, time(9, random.randint(0, 30))),
                                check_out=datetime.combine(day, time(18, random.randint(0, 40))),
                                status=HomeOfficeEntry.Status.APPROVED,
                            ),
                        )
                        continue
                    if roll < 0.32:  # late
                        in_dt = datetime.combine(day, time(10, random.randint(1, 45)))
                    else:
                        in_dt = datetime.combine(day, time(8 if random.random() < .3 else 9,
                                                          random.randint(0, 55)))
                    record_punch(employee=emp, punch_time=in_dt, card_no=emp.rfid_card_no,
                                 device_user_id=emp.device_user_id)
                    required = max(datetime.combine(day, shift.end_time), in_dt + timedelta(hours=9))
                    delta = random.choice([-75, -20, 3, 8, 25, 60])
                    out_dt = required + timedelta(minutes=delta)
                    if day < today or out_dt.time() < app_now().time():
                        record_punch(employee=emp, punch_time=out_dt, card_no=emp.rfid_card_no,
                                     device_user_id=emp.device_user_id)
                    if random.random() < 0.7:
                        DailyTask.objects.get_or_create(
                            employee=emp, date=day, title=random.choice(TASKS),
                            defaults=dict(hours_spent=random.choice([2, 3, 4, 6, 8]),
                                          project=random.choice(["Internal", "Client-A", "Client-B"])),
                        )
            day += timedelta(days=1)

        Holiday.objects.get_or_create(date=today + timedelta(days=6), defaults={"title": "Company Day"})
        ct = LeaveType.objects.first()
        for emp in employees[:3]:
            LeaveRequest.objects.get_or_create(
                employee=emp, leave_type=ct, start_date=today + timedelta(days=3),
                end_date=today + timedelta(days=4), defaults={"reason": "Family event"},
            )

        rebuild_range(start, today)
        self.stdout.write(self.style.SUCCESS(
            "Demo data created.\n"
            "  admin / admin123    -> admin dashboard\n"
            "  rakib1 / pass1234   -> employee portal"
        ))
