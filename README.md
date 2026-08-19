# Office Attendance System — ZKTeco F18 + RFID

A Django (MVT) attendance system: RFID card punches from a ZKTeco F18, an admin
dashboard, a personal portal for every employee, daily task logging, leave
requests, home office entries and a full set of reports.

---

## 1. The attendance rules

| Item | Rule |
|---|---|
| Office hours | 9:00 AM – 6:00 PM = **9 hours** |
| Late | A punch after **10:00 AM** is marked late |
| Required out | `max(6:00 PM, in-time + 9 hours)` |
| Example | In at 10:02 AM → required out **7:02 PM** |
| Early out | Leaving **before** the required out time |
| Late + early | Both together get their own status, `LATE_EARLY` |
| Half day | Less than 4 hours worked |
| Missing out | An in-punch with no matching out-punch |
| Overtime | Anything worked past the required out time |

Every number above comes from the **Shift** model (Setup → Shift & rules), so the
office policy can be changed without touching the code.

> **One decision worth confirming:** by default the 9 hours are *always*
> required — arriving at 9:45 AM means leaving at 6:45 PM. If you would rather
> let anyone who arrives before 10:00 AM leave at 6:00 PM, switch on
> **"Extend only when late"** in the shift settings.

The rules are covered by 16 automated tests:

```bash
python manage.py test apps.attendance
```

---

## 2. Running the project

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_demo          # demo employees + 20 days of punches
python manage.py runserver
```

Open <http://127.0.0.1:8000>

| Login | Password | What you get |
|---|---|---|
| `admin` | `admin123` | Admin dashboard and all reports |
| `rakib1` | `pass1234` | Employee portal |

To start clean instead of seeding demo data:

```bash
python manage.py createsuperuser
```

Then go to Setup → Shift & rules and create a shift (9:00 AM, 6:00 PM, late
after 10:00 AM, 9 required hours).

---

## 3. Assigning RFID cards

1. **People → Employees → Add employee** to create the employee record.
2. On that employee's page, enter the card ID in the **RFID card** box and save.
   (Or use **People → RFID cards** to fill in every card ID on one screen.)
3. Duplicate card IDs are rejected automatically.
4. If the card numbers are already stored on the device, **Devices → Pull card
   IDs** copies them into the employee records.

**How a punch is matched:** by `rfid_card_no` **or** `device_user_id` — either
one is enough. Anything that matches neither is kept as an *unmatched* punch,
and an admin can link it to an employee from the **Punch logs** page.

---

## 4. Connecting the ZKTeco F18

```bash
pip install pyzk
```

Go to **Devices → Add device** and enter a name, the IP address (e.g.
`192.168.1.201`), port `4370`, and the COMM key if one is set on the device.

The buttons on each device card:

- **Sync punches** — pulls all punch logs from the device
- **Pull card IDs** — reads card numbers from the device user list
- **Set device time** — syncs the device clock with the server

Automatic syncing via cron:

```cron
*/10 * * * * cd /path/to/project && /path/to/venv/bin/python manage.py sync_devices
5 21 * * *  cd /path/to/project && /path/to/venv/bin/python manage.py process_attendance --days 2
```

If the device is unreachable, use **CSV import** instead. Required columns:
`card_no` (or `device_user_id`) and `punch_time` (`YYYY-MM-DD HH:MM:SS`).

---

## 5. The employee portal

- **My day** — today's in time, required out time, out time, the punch tape and
  a summary of the month
- **Daily tasks** — what was worked on each day (title, project, hours, progress)
- **My attendance** — a monthly calendar plus a day-by-day list
- **Leave request** — submit, track status, see the remaining balance
- **Home office** — for anyone not coming in: pick the date, give a reason and an
  **in time**, then log the **out time** when finished. Once an admin approves
  it, the day appears on the attendance sheet in Home office mode, under exactly
  the same 9-hour rule.

Employees working from the office do nothing but punch on the reader.

---

## 6. Admin dashboard and reports

- **Dashboard** — on time / late / absent / home office counts, who is still in
  the office, a seven-day trend and pending approvals
- **Attendance sheet** — filter by date range, department and status; edit any
  record by hand
- **Punch logs** — raw punches, manual punch entry, linking unmatched punches
- **Monthly sheet** — a colour-coded employee × day grid for the whole month
- **Employee report** — one person's day-by-day detail plus their tasks
- **Late & early out** — who was late, how often and by how many minutes
- **Department summary** — punctuality percentage per department
- **Exports** — Excel (.xlsx) and CSV for payroll

---

## 7. Project structure (MVT)

```
core/                 settings, root urls
apps/
  accounts/           User (employee + RFID card), Department, Designation, Shift
  attendance/         PunchLog, DailyAttendance, HomeOfficeEntry, Holiday
    rules.py          <- the office policy (pure functions, fully tested)
    services.py       <- turns punches into DailyAttendance
  devices/            Device, zk_service.py (pyzk), CSV import
  leaves/             LeaveType, LeaveRequest
  tasks/              DailyTask
  reports/            report views + Excel/CSV export
templates/            all HTML (base + partials + per app)
static/css/app.css    the design system
```

**Data flow:** `Device → PunchLog → services.rebuild_day() → rules.evaluate_day() → DailyAttendance → reports`

Adding or deleting a punch, or approving a home office entry, triggers a signal
that recalculates that day automatically.

---

## 8. Before going to production

1. Set `DJANGO_SECRET_KEY` and `DJANGO_DEBUG=0` (see `.env.example`).
2. Move from SQLite to MySQL or PostgreSQL in `core/settings.py` → `DATABASES`.
3. Run `python manage.py collectstatic`, then serve with gunicorn + nginx.
4. Set `ALLOWED_HOSTS` correctly and enable HTTPS.
5. Install the two cron jobs shown above.
6. Schedule regular database backups.

> `USE_TZ = False` is deliberate — attendance maths (in/out times, the 9-hour
> rule) is simpler and less error-prone in local naive time.
> `TIME_ZONE = "Asia/Dhaka"`.
