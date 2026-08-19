"""Service layer that talks to the ZKTeco F18.

Uses the `pyzk` library:  pip install pyzk
The project runs fine without it - manual entry and CSV import still work,
and any sync attempt returns a clear error message instead of crashing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

try:  # pragma: no cover - device library optional
    from zk import ZK
    ZK_AVAILABLE = True
except Exception:  # pragma: no cover
    ZK = None
    ZK_AVAILABLE = False


class DeviceError(Exception):
    pass


@dataclass
class RawPunch:
    device_user_id: str
    timestamp: datetime
    status: int = 0
    punch: int = 0


@dataclass
class DeviceUser:
    device_user_id: str
    name: str
    card_no: str
    privilege: int = 0


def _connect(device):
    if not ZK_AVAILABLE:
        raise DeviceError(
            "The pyzk library is not installed. Run:  pip install pyzk"
        )
    zk = ZK(
        device.ip_address,
        port=device.port,
        timeout=device.timeout,
        password=int(device.comm_password) if str(device.comm_password).isdigit() else 0,
        force_udp=device.force_udp,
        ommit_ping=True,
    )
    try:
        return zk.connect()
    except Exception as exc:  # pragma: no cover
        raise DeviceError(f"Could not connect to the device: {exc}") from exc


def fetch_attendance(device) -> list[RawPunch]:
    """Fetch every punch log stored on the device."""
    conn = _connect(device)
    try:
        conn.disable_device()
        records = conn.get_attendance() or []
        punches = [
            RawPunch(
                device_user_id=str(r.user_id),
                timestamp=r.timestamp,
                status=getattr(r, "status", 0) or 0,
                punch=getattr(r, "punch", 0) or 0,
            )
            for r in records
        ]
        if device.clear_after_sync:
            conn.clear_attendance()
        return punches
    finally:  # pragma: no cover
        try:
            conn.enable_device()
            conn.disconnect()
        except Exception:
            pass


def fetch_users(device) -> list[DeviceUser]:
    """The device user list - this is where RFID card numbers come from."""
    conn = _connect(device)
    try:
        conn.disable_device()
        return [
            DeviceUser(
                device_user_id=str(u.user_id),
                name=u.name or "",
                card_no=str(getattr(u, "card", "") or "").strip(),
                privilege=getattr(u, "privilege", 0) or 0,
            )
            for u in (conn.get_users() or [])
        ]
    finally:  # pragma: no cover
        try:
            conn.enable_device()
            conn.disconnect()
        except Exception:
            pass


def push_user(device, employee) -> None:
    """Push an employee and their card ID from the dashboard to the device."""
    conn = _connect(device)
    try:
        conn.disable_device()
        conn.set_user(
            uid=int(employee.device_user_id or employee.pk),
            name=(employee.display_name or "")[:24],
            privilege=0,
            user_id=str(employee.device_user_id or employee.pk),
            card=int(employee.rfid_card_no) if str(employee.rfid_card_no or "").isdigit() else 0,
        )
    finally:  # pragma: no cover
        try:
            conn.enable_device()
            conn.disconnect()
        except Exception:
            pass


def device_time(device) -> datetime:
    conn = _connect(device)
    try:
        return conn.get_time()
    finally:  # pragma: no cover
        conn.disconnect()


def sync_device_time(device) -> datetime:
    conn = _connect(device)
    try:
        now = datetime.now()
        conn.set_time(now)
        return now
    finally:  # pragma: no cover
        conn.disconnect()
