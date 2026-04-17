#!/usr/bin/env python3
"""Aranet4 Bluetooth Data Logger with SQLite storage."""

import argparse
import asyncio
import errno
import fcntl
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import aranet4
from bleak.exc import BleakDBusError
from dotenv import load_dotenv

# Validation ranges
VALID_RANGES = {
    "co2_ppm": (400, 5000),
    "temperature_c": (-10.0, 50.0),
    "humidity_percent": (0, 100),
    "pressure_hpa": (900.0, 1100.0),
    "battery_percent": (0, 100),
}

logger = logging.getLogger("aranet_logger")


class BluezScanConflictError(Exception):
    """BlueZ scan still InProgress after StopDiscovery, bluetooth restart, and retries."""


def setup_logging() -> None:
    """Configure logging for systemd journal compatibility."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def load_config() -> tuple[str, str, int]:
    """Load configuration from .env file next to this script."""
    script_dir = Path(__file__).resolve().parent
    load_dotenv(script_dir / ".env")
    mac = os.getenv("ARANET_MAC", "").strip()
    db_path = os.getenv("DB_PATH", str(script_dir / "aranet.db")).strip()
    poll_interval = int(os.getenv("POLL_INTERVAL", "60"))
    return mac, db_path, poll_interval


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize SQLite database and create table if not exists."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS aranet_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            co2_ppm INTEGER,
            temperature_c REAL,
            humidity_percent REAL,
            pressure_hpa REAL,
            battery_percent INTEGER
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_timestamp ON aranet_readings(timestamp)"
    )
    conn.commit()
    return conn


def reset_bluetooth_adapter() -> None:
    """Reset the Bluetooth adapter to clear stuck scan state in bluez.

    Uses systemctl to restart the bluetooth service, which clears any
    stuck scan state in bluez. Requires a sudoers rule (no password):
        ian ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart bluetooth
    """
    logger.warning("Resetting Bluetooth adapter to clear stuck scan...")
    try:
        subprocess.run(
            ["sudo", "-n", "systemctl", "restart", "bluetooth"],
            check=True, timeout=15, capture_output=True,
        )
        time.sleep(5)  # give bluez time to reinitialize before callers scan again
        logger.info("Bluetooth adapter reset complete")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.error("Failed to reset Bluetooth adapter: %s", exc)


def _clear_bluez_le_discovery() -> None:
    """Ask BlueZ to end any active LE discovery (fixes ghost ``InProgress`` state).

    ``org.bluez.Error.InProgress`` on ``StartDiscovery`` often means discovery was
    left running by a crashed client or another tool — ``systemctl restart bluetooth``
    alone does not always clear it before our process runs again. Optional env:
    ``BLUEZ_ADAPTER_DBUS_PATH`` (default ``/org/bluez/hci0``).
    """
    hci = os.environ.get("BLUEZ_ADAPTER_DBUS_PATH", "/org/bluez/hci0")
    for args in (
        [
            "dbus-send",
            "--system",
            "--type=method_call",
            "--dest=org.bluez",
            hci,
            "org.bluez.Adapter1.StopDiscovery",
        ],
        ["bluetoothctl", "--timeout", "3", "scan", "off"],
    ):
        try:
            subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=6,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def _is_bluez_in_progress(exc: BaseException) -> bool:
    if isinstance(exc, BleakDBusError):
        return getattr(exc, "dbus_error", "") == "org.bluez.Error.InProgress"
    text = str(exc)
    return "InProgress" in text or "org.bluez.Error.InProgress" in text


def _scan_aranet4(mac: str) -> dict | None:
    """Perform a single BLE advertisement scan for the Aranet4 device."""
    result = {}

    def on_advertisement(ad):
        if ad.device and ad.device.address.upper() == mac.upper() and ad.readings:
            result["reading"] = ad.readings

    aranet4.client.find_nearby(on_advertisement, duration=10)

    if "reading" not in result:
        return None
    return result["reading"]


def _reading_dict_from_scan_result(current) -> dict:
    """Build the DB/log reading dict from aranet4 readings object or recovery JSON dict."""
    if isinstance(current, dict):
        return current
    return {
        "co2_ppm": current.co2,
        "temperature_c": current.temperature,
        "humidity_percent": current.humidity,
        "pressure_hpa": current.pressure,
        "battery_percent": current.battery,
    }


def _scan_via_fresh_process_after_bluetooth_restart() -> dict | None:
    """Run one BLE scan in a new interpreter (clean Bleak/D-Bus after bluetoothd restart).

    The parent process can keep a stale D-Bus view after ``systemctl restart bluetooth``,
    so ``find_nearby`` keeps returning ``InProgress`` even when the adapter is idle.
    """
    script = Path(__file__).resolve()
    cp = subprocess.run(
        [sys.executable, str(script), "--ble-recovery-scan"],
        cwd=str(script.parent),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if cp.returncode != 0:
        tail = ((cp.stderr or "").strip() or (cp.stdout or "").strip())[:400]
        logger.warning("Fresh-process BLE scan failed rc=%s: %s", cp.returncode, tail)
        return None
    line = (cp.stdout or "").strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        logger.warning("Fresh-process BLE scan: invalid JSON: %r", line[:200])
        return None


def run_ble_recovery_scan() -> None:
    """Entry point for ``--ble-recovery-scan`` (stdout = one JSON object, then exit)."""
    setup_logging()
    mac, _, _ = load_config()
    if not mac:
        print("", flush=True)
        sys.exit(2)
    _clear_bluez_le_discovery()
    try:
        data = _scan_aranet4(mac)
    except Exception as exc:
        logger.error("ble-recovery-scan failed: %s", exc)
        print("", flush=True)
        sys.exit(1)
    if data is None:
        print("", flush=True)
        sys.exit(1)
    reading = _reading_dict_from_scan_result(data)
    print(json.dumps(reading), flush=True)
    sys.exit(0)


def read_aranet4(mac: str) -> dict | None:
    """Read current measurements from Aranet4 via BLE advertisement scan.

    Uses find_nearby() which reads from BLE advertisements — no GATT
    connection required. More reliable than direct connect on Linux/bluez.

    If BlueZ returns ``InProgress``, we first call ``StopDiscovery`` /
    ``bluetoothctl scan off`` (orphaned discovery is a common cause), retry
    the scan once, then restart the bluetooth service. The next attempt runs
    ``find_nearby`` in a **fresh Python subprocess** so Bleak/D-Bus match the
    restarted bluetoothd; only if that and a final in-process try fail do we
    raise :class:`BluezScanConflictError`.
    """
    logger.info("Scanning for Aranet4 (%s)...", mac)
    _clear_bluez_le_discovery()

    try:
        current = _scan_aranet4(mac)
    except Exception as exc:
        if not _is_bluez_in_progress(exc):
            raise
        logger.warning(
            "BlueZ InProgress on scan start — clearing stale LE discovery, then retrying"
        )
        _clear_bluez_le_discovery()
        try:
            current = _scan_aranet4(mac)
        except Exception as exc2:
            if not _is_bluez_in_progress(exc2):
                raise
            logger.warning(
                "Still InProgress after StopDiscovery — restarting bluetooth, then retrying"
            )
            reset_bluetooth_adapter()
            _clear_bluez_le_discovery()
            time.sleep(5)
            logger.info(
                "Retrying BLE scan in a fresh Python process (clean D-Bus after bluetooth restart)"
            )
            recovery = _scan_via_fresh_process_after_bluetooth_restart()
            if recovery is not None:
                current = recovery
            else:
                try:
                    current = _scan_aranet4(mac)
                except Exception as exc3:
                    if not _is_bluez_in_progress(exc3):
                        raise
                    raise BluezScanConflictError(
                        "BLE scan still blocked after StopDiscovery + bluetooth restart + "
                        "fresh-process retry + in-process retry. Another process may be "
                        "scanning — check: ps aux | grep -E 'aranet_logger|bleak'; verify "
                        "BLUEZ_ADAPTER_DBUS_PATH matches `busctl tree org.bluez`."
                    ) from exc3

    if current is None:
        logger.error("Aranet4 (%s) not found during scan", mac)
        return None

    reading = _reading_dict_from_scan_result(current)

    logger.info(
        "CO2=%d ppm  Temp=%.1f°C  Humidity=%d%%  Pressure=%.1f hPa  Battery=%d%%",
        reading["co2_ppm"],
        reading["temperature_c"],
        reading["humidity_percent"],
        reading["pressure_hpa"],
        reading["battery_percent"],
    )

    return reading


def validate_reading(reading: dict) -> bool:
    """Validate reading values against expected ranges."""
    for key, (low, high) in VALID_RANGES.items():
        value = reading.get(key)
        if value is None or not (low <= value <= high):
            logger.warning(
                "Validation failed: %s=%s (expected %s-%s)", key, value, low, high
            )
            return False
    return True


def insert_reading(conn: sqlite3.Connection, reading: dict) -> None:
    """Insert a validated reading into the database with retry on lock."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            conn.execute(
                """
                INSERT INTO aranet_readings
                    (co2_ppm, temperature_c, humidity_percent, pressure_hpa, battery_percent)
                VALUES
                    (:co2_ppm, :temperature_c, :humidity_percent, :pressure_hpa, :battery_percent)
                """,
                reading,
            )
            conn.commit()
            return
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc) and attempt < max_retries - 1:
                logger.warning(
                    "Database locked, retrying (%d/%d)", attempt + 1, max_retries
                )
                time.sleep(0.5 * (attempt + 1))
            else:
                raise


# ── Single-shot mode ──────────────────────────────────────────────────────────


LOCK_PATH = Path("/tmp/aranet4-dash.lock")


def _lock_holder_message() -> str:
    """Best-effort hint when the lock file is busy (Linux: pid in file)."""
    try:
        raw = LOCK_PATH.read_text(encoding="utf-8").strip().split()
        if not raw:
            return (
                f"lock busy; {LOCK_PATH} empty (holder between flock and pid write, "
                "or old logger); try: ps aux | grep aranet_logger"
            )
        pid = int(raw[0])
    except (OSError, ValueError):
        return f"lock busy; could not parse pid from {LOCK_PATH}"

    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return (
                f"lock busy; {LOCK_PATH} lists pid {pid} but that process is gone "
                "(retry in a second)"
            )
        if exc.errno == errno.EPERM:
            return f"lock busy; pid {pid} exists (inspect with sudo ps -p {pid})"
        raise
    return f"pid {pid} holds the lock (e.g. cron); inspect: ps -p {pid} -o args="


def single_reading(mac: str, db_path: str) -> None:
    """Take a single reading and exit. Uses a file lock to prevent overlapping runs."""
    # Open without truncating so we do not wipe another process's pid before flock.
    lock_file = open(LOCK_PATH, "a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        logger.warning("Another instance is already running, skipping — %s", _lock_holder_message())
        sys.exit(0)

    # Write pid before truncating so the file is never empty while we hold the lock.
    lock_file.seek(0)
    lock_file.write(f"{os.getpid()}\n")
    lock_file.flush()
    lock_file.truncate()

    try:
        conn = init_db(db_path)
        try:
            try:
                reading = read_aranet4(mac)
            except BluezScanConflictError as exc:
                logger.error("%s", exc)
                sys.exit(1)

            if reading is None:
                logger.error("Failed to read from Aranet4")
                sys.exit(1)

            if validate_reading(reading):
                insert_reading(conn, reading)
                logger.info("Reading saved to database")
            else:
                logger.warning("Reading failed validation, not saved")
        finally:
            conn.close()
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


# ── Main polling loop ─────────────────────────────────────────────────────────


async def main_loop(mac: str, db_path: str, poll_interval: int) -> None:
    """Main polling loop with exponential backoff on errors."""
    conn = init_db(db_path)

    backoff = 1
    max_backoff = 300  # 5 minutes cap
    readings_since_vacuum = 0

    shutdown = asyncio.Event()

    def handle_signal() -> None:
        logger.info("Shutdown signal received")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    logger.info(
        "Starting Aranet4 logger: MAC=%s, DB=%s, interval=%ds",
        mac,
        db_path,
        poll_interval,
    )

    try:
        while not shutdown.is_set():
            try:
                reading = read_aranet4(mac)
                if reading is None:
                    raise RuntimeError("Empty reading from Aranet4")

                if validate_reading(reading):
                    insert_reading(conn, reading)
                    readings_since_vacuum += 1
                else:
                    logger.warning("Reading failed validation, skipping insert")

                # Reset backoff after a successful cycle
                backoff = 1

                # Periodic vacuum every ~1000 readings
                if readings_since_vacuum >= 1000:
                    logger.info("Running VACUUM on database")
                    conn.execute("VACUUM")
                    readings_since_vacuum = 0

            except BluezScanConflictError as exc:
                logger.warning("%s", exc)
                delay = min(backoff, max_backoff)
                logger.info("Retrying in %ds", delay)
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=delay)
                    break  # shutdown signalled during backoff
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, max_backoff)
                continue

            except Exception:
                logger.exception("Error during read cycle")
                delay = min(backoff, max_backoff)
                logger.info("Retrying in %ds", delay)
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=delay)
                    break  # shutdown signalled during backoff
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, max_backoff)
                continue

            # Wait for next poll or shutdown
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=poll_interval)
                break  # shutdown signalled during sleep
            except asyncio.TimeoutError:
                pass
    finally:
        conn.close()
        logger.info("Aranet4 logger stopped")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    setup_logging()
    mac, db_path, poll_interval = load_config()

    parser = argparse.ArgumentParser(description="Aranet4 Bluetooth Data Logger")
    parser.add_argument(
        "--single",
        action="store_true",
        help="Take a single reading and exit (for testing)",
    )
    parser.add_argument(
        "--ble-recovery-scan",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    if args.ble_recovery_scan:
        run_ble_recovery_scan()  # always sys.exit

    if args.single:
        single_reading(mac, db_path)
    else:
        asyncio.run(main_loop(mac, db_path, poll_interval))


if __name__ == "__main__":
    main()
