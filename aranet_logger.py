#!/usr/bin/env python3
"""Aranet4 Bluetooth Data Logger with SQLite storage."""

import argparse
import asyncio
import fcntl
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
    """BlueZ scan InProgress after adapter restart — need a fresh OS process to scan."""


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
        time.sleep(3)  # give bluez time to reinitialize
        logger.info("Bluetooth adapter reset complete")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.error("Failed to reset Bluetooth adapter: %s", exc)


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


def read_aranet4(mac: str) -> dict | None:
    """Read current measurements from Aranet4 via BLE advertisement scan.

    Uses find_nearby() which reads from BLE advertisements — no GATT
    connection required. More reliable than direct connect on Linux/bluez.
    If bluez reports ``InProgress``, restarts the bluetooth service (see
    ``reset_bluetooth_adapter``) and raises :class:`BluezScanConflictError`
    so the caller exits and the next cron invocation runs in a new process.
    Retrying ``find_nearby`` in the same interpreter after ``restart
    bluetooth`` often fails again because Bleak/DBus client state is stale.
    """
    logger.info("Scanning for Aranet4 (%s)...", mac)

    try:
        current = _scan_aranet4(mac)
    except BleakDBusError as exc:
        if getattr(exc, "dbus_error", "") == "org.bluez.Error.InProgress":
            reset_bluetooth_adapter()
            logger.info(
                "Exiting this process without rescanning here (Bleak stays safer "
                "after a bluetooth restart when the next run is a new interpreter). "
                "Run --single again, or wait for cron."
            )
            raise BluezScanConflictError(
                "First scan: org.bluez.Error.InProgress (another LE scan or stuck "
                "bluez). Bluetooth was restarted above, then this run ends. "
                "Run `uv run aranet_logger.py --single` once more. If the next run "
                "still opens with InProgress, stop other BLE jobs on the Pi "
                "(e.g. pkill -f airlab_collector), then sudo systemctl restart bluetooth."
            ) from exc
        raise
    except Exception as exc:
        if "InProgress" in str(exc) or "org.bluez.Error.InProgress" in str(exc):
            reset_bluetooth_adapter()
            logger.info(
                "Exiting without rescan in-process; run --single again or wait for cron."
            )
            raise BluezScanConflictError(
                "First scan: InProgress (wrapped error). Bluetooth was restarted; "
                "exit and retry like BleakDBusError InProgress."
            ) from exc
        raise

    if current is None:
        logger.error("Aranet4 (%s) not found during scan", mac)
        return None

    reading = {
        "co2_ppm": current.co2,
        "temperature_c": current.temperature,
        "humidity_percent": current.humidity,
        "pressure_hpa": current.pressure,
        "battery_percent": current.battery,
    }

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


def single_reading(mac: str, db_path: str) -> None:
    """Take a single reading and exit. Uses a file lock to prevent overlapping runs."""
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.warning("Another instance is already running, skipping")
        sys.exit(0)

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
    args = parser.parse_args()

    if args.single:
        single_reading(mac, db_path)
    else:
        asyncio.run(main_loop(mac, db_path, poll_interval))


if __name__ == "__main__":
    main()
