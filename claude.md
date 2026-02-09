# Aranet4 Bluetooth Data Logger

## What this is
Python script that reads CO2, temperature, humidity, pressure, and battery from an Aranet4 sensor via Bluetooth LE and stores readings in SQLite. Runs on a Raspberry Pi (fish shell), scheduled via crontab. Grafana dashboards via the SQLite plugin.

## Tech stack
- Python 3.9+ managed with [uv](https://docs.astral.sh/uv/)
- `bleak` (BLE) and `python-dotenv` (config)
- SQLite via stdlib `sqlite3`
- Grafana + `frser-sqlite-datasource` plugin for dashboards
- crontab for scheduling (every minute)
- Raspberry Pi runs fish shell

## Project structure
```
/home/ian/dev/aranet4-dash/
├── .cursor/rules/use-uv.mdc  # Cursor rule: always use uv for Python
├── .env.example               # Template config (committed)
├── .env                       # Actual config (gitignored)
├── .gitignore
├── aranet_logger.py           # Main script
├── pyproject.toml             # Python dependencies (uv)
├── README.md                  # Full setup instructions
└── claude.md                  # This file (AI context)
```

## Database schema
Table `aranet_readings` in SQLite:
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `timestamp` DATETIME DEFAULT CURRENT_TIMESTAMP
- `co2_ppm` INTEGER
- `temperature_c` REAL
- `humidity_percent` REAL
- `pressure_hpa` REAL
- `battery_percent` INTEGER
- Index on `timestamp`

## Key decisions
- **uv for Python**: All dependency management and script execution via `uv sync` / `uv run`. No manual venv or pip.
- **Crontab**: Script runs in `--single` mode per invocation. Simpler than a daemon — no long-running process to manage.
- **`.env` resolved relative to script**: `load_dotenv()` uses the script's own directory, so cron jobs work regardless of cwd.
- **Byte layout from spec**: 7-byte packet parsed in `parse_reading()`. If actual device returns different data (some firmware versions use uint16 LE for temp/pressure across more bytes), adjust offsets there.
- **Validation**: Strict ranges per spec (CO2 400-5000, temp -10-50C, humidity 0-100%, pressure 900-1100 hPa, battery 0-100%). Readings outside range are logged and skipped.
- **Grafana SQLite plugin**: Reads the `.db` file directly — no intermediate server needed.

## Config (.env)
- `ARANET_MAC` - Bluetooth MAC of Aranet4 (use `bluetoothctl scan on` to find)
- `DB_PATH` - Path to SQLite database file (default: `aranet.db` next to script)
- `POLL_INTERVAL` - Seconds between readings in daemon mode (default 60, not used by crontab)

## Current status
- Initial implementation complete, not yet tested against real hardware.
