---
name: python-project
description: Python conventions for the aranet4-dash project. Use when editing aranet_logger.py or adding Python code — covers config loading, validation, BLE scanning, database access, and logging patterns.
---

# Python project conventions

## Config

- All user config lives in `.env` (gitignored), loaded via `python-dotenv`.
- `.env` is resolved relative to the script's own directory (`Path(__file__).resolve().parent`), so cron jobs work regardless of cwd.
- `.env.example` is the committed template — keep it in sync when adding new config vars.

## BLE scanning

- Use `aranet4.client.find_nearby(callback, duration=10)` for BLE advertisement scan.
- Do **not** use GATT direct connect (`aranet4.client.get_current_readings()`) — it hangs on Linux/bluez for this device.
- The Aranet4 must have **Smart Home integrations** enabled in the Aranet Home app.

## Validation

Strict ranges — readings outside these are logged and skipped, never inserted:

| Field              | Min   | Max   |
|--------------------|-------|-------|
| `co2_ppm`          | 400   | 5000  |
| `temperature_c`    | -10.0 | 50.0  |
| `humidity_percent`  | 0     | 100   |
| `pressure_hpa`     | 900.0 | 1100.0|
| `battery_percent`  | 0     | 100   |

## Database

- SQLite via stdlib `sqlite3`. No ORM.
- Single table `aranet_readings` with `timestamp DATETIME DEFAULT CURRENT_TIMESTAMP`.
- Retry on `database is locked` (up to 3 attempts with backoff) since Grafana may be reading concurrently.
- `VACUUM` runs every ~1000 readings in daemon mode.

## Logging

- Use `logging` stdlib, not `print()`.
- Format: `%(asctime)s %(levelname)s %(message)s` with `%Y-%m-%d %H:%M:%S`.
- Log to stdout — cron redirects to `cron.log`, systemd captures via journal.

## Modes

- `--single`: one reading then exit (used by crontab).
- Default: async polling loop with exponential backoff on errors and graceful SIGTERM/SIGINT handling.
