# Aranet4 Bluetooth Data Logger

## What this is
Python script that reads CO2, temperature, humidity, pressure, and battery from an Aranet4 sensor via BLE advertisement scan and stores readings in SQLite. Runs on a Raspberry Pi (fish shell), scheduled via crontab. Grafana dashboards via the SQLite plugin.

## Tech stack
- Python 3.9+ managed with [uv](https://docs.astral.sh/uv/)
- `aranet4` library (handles BLE scan and data parsing) and `python-dotenv` (config)
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
├── grafana/
│   └── dashboard.json         # Grafana dashboard (import via UI)
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
- **BLE advertisement scan**: Uses `aranet4.client.find_nearby()` to read from BLE advertisements. No GATT connection needed — more reliable on Linux/bluez than direct connect (which hangs on this device). Requires "Smart Home integrations" enabled in the Aranet Home app.
- **Validation**: Strict ranges (CO2 400-5000, temp -10-50C, humidity 0-100%, pressure 900-1100 hPa, battery 0-100%). Readings outside range are logged and skipped.
- **Grafana SQLite plugin**: Reads the `.db` file directly — no intermediate server needed.
- **Dashboard JSON**: `grafana/dashboard.json` is the exported working dashboard. Import via Dashboards > Import in Grafana. Time series queries use `CAST(strftime('%s', timestamp) AS INTEGER)` because the SQLite plugin needs Unix epoch numbers, not datetime strings.

## Config (.env)
- `ARANET_MAC` - Bluetooth MAC of Aranet4 ("Smart Home integrations" must be enabled in Aranet Home app)
- `DB_PATH` - Path to SQLite database file (default: `/var/lib/aranet4-dash/aranet.db`, shared with Grafana via `grafana` group)
- `POLL_INTERVAL` - Seconds between readings in daemon mode (default 60, not used by crontab)

## Current status
- BLE advertisement scan confirmed working on Raspberry Pi. GATT direct connect does not work (hangs on service discovery).
