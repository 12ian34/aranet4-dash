# Aranet4 Bluetooth Data Logger

Read CO2, temperature, humidity, pressure, and battery from an [Aranet4](https://aranet.com/products/aranet4/) sensor over Bluetooth LE and log to a local SQLite database. Visualise with Grafana.

Designed to run on a Raspberry Pi via crontab.

## Prerequisites

- Raspberry Pi (tested on Pi 4 / Pi 5) with Bluetooth
- Raspberry Pi OS (Bookworm or later)
- Python 3.9+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- An Aranet4 sensor within Bluetooth range
- **Smart Home integrations** enabled in the [Aranet Home](https://aranet.com/aranet-home-app) phone app (device settings) — required for BLE data access

All shell commands below work in both bash and fish.

## 1. Clone and install

```sh
cd /home/ian/dev
git clone <repo-url> aranet4-dash
cd aranet4-dash
uv sync
```

That's it — `uv sync` creates the venv and installs dependencies from `pyproject.toml`.

## 2. Find your Aranet4 MAC address

Make sure the Aranet4 is nearby.

```sh
uv run aranetctl --scan
```

Look for your device in the output:

```
=======================================
  Name:     Aranet4 0A3D9
  Address:  AA:BB:CC:DD:EE:FF
  RSSI:     -83 dBm
---------------------------------------
  CO2:            593 ppm
  Temperature:    19.0 °C
  ...
```

Note the MAC address. If no readings appear, make sure **Smart Home integrations** is enabled in the Aranet Home app.

## 3. Create the database directory

```sh
sudo mkdir -p /var/lib/aranet4-dash
sudo chown ian:grafana /var/lib/aranet4-dash
chmod 750 /var/lib/aranet4-dash
```

This keeps the DB outside your home directory so Grafana (`grafana` user) can read it via group permissions without exposing anything else.

## 4. Configure

Copy the example and fill in your values:

```sh
cp .env.example .env
nano .env
```

```env
ARANET_MAC=AA:BB:CC:DD:EE:FF
DB_PATH=/var/lib/aranet4-dash/aranet.db
POLL_INTERVAL=60
```

- `ARANET_MAC` — the MAC address from step 2
- `DB_PATH` — where to store the SQLite database
- `POLL_INTERVAL` — seconds between readings in daemon mode (default 60, not used by crontab)

## 5. Test a single reading

```sh
cd /home/ian/dev/aranet4-dash
uv run aranet_logger.py --single
```

You should see output like:

```
2026-02-09 12:00:00 INFO Scanning for Aranet4 (AA:BB:CC:DD:EE:FF)...
2026-02-09 12:00:10 INFO CO2=593 ppm  Temp=19.0°C  Humidity=56%  Pressure=998.2 hPa  Battery=96%
2026-02-09 12:00:10 INFO Reading saved to database
```

## 6. Verify the database

```sh
sqlite3 /var/lib/aranet4-dash/aranet.db
```

```sql
SELECT * FROM aranet_readings ORDER BY timestamp DESC LIMIT 5;
.quit
```

## 7. Set up crontab

Cron always uses `/bin/sh`, so fish vs bash doesn't matter here.

```sh
crontab -e
```

Add these lines to poll every minute:

```cron
PATH=/home/ian/.local/bin:/usr/local/bin:/usr/bin:/bin

* * * * * cd /home/ian/dev/aranet4-dash && uv run aranet_logger.py --single >> /home/ian/dev/aranet4-dash/cron.log 2>&1
```

The `PATH` line ensures cron can find `uv`. Save and exit, then verify:

```sh
crontab -l
```

Check it's working after a few minutes:

```sh
tail -f /home/ian/dev/aranet4-dash/cron.log
```

## 8. Install Grafana

```sh
sudo apt-get install -y apt-transport-https software-properties-common
sudo mkdir -p /etc/apt/keyrings/
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update
sudo apt-get install -y grafana
```

Start and enable:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now grafana-server
```

Grafana is now running at `http://<pi-ip>:3000`. Default login is `admin` / `admin`.

## 9. Install the SQLite datasource plugin

```sh
sudo grafana-cli plugins install frser-sqlite-datasource
sudo systemctl restart grafana-server
```

## 10. Configure the datasource

1. Open Grafana at `http://<pi-ip>:3000`
2. Go to **Connections > Data sources > Add data source**
3. Search for **SQLite**
4. Set the path to:
   ```
   /var/lib/aranet4-dash/aranet.db
   ```
5. Click **Save & test** — should say "Data source is working"

## 11. Import the dashboard

A pre-built dashboard JSON is included in the repo at `grafana/dashboard.json`.

1. In Grafana, go to **Dashboards > New > Import**
2. Click **Upload JSON file** and select `grafana/dashboard.json` from the repo
3. Click **Import**

The dashboard includes:

- **Bar gauge** — latest reading for CO2, Temperature, Humidity, Pressure, Battery with colour-coded thresholds
- **CO2 time series** — with green/yellow/red threshold bands at 800/1000 ppm
- **Temperature time series** — orange line, 10-35 C range
- **Humidity time series** — blue line, 0-100% range
- **Pressure time series** — purple line, 950-1050 hPa range

> **Note:** The time series queries use `CAST(strftime('%s', timestamp) AS INTEGER)` to convert timestamps to Unix epoch — the SQLite plugin requires numeric timestamps for time series charts.

## Database schema

```sql
CREATE TABLE IF NOT EXISTS aranet_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    co2_ppm INTEGER,
    temperature_c REAL,
    humidity_percent REAL,
    pressure_hpa REAL,
    battery_percent INTEGER
);

CREATE INDEX IF NOT EXISTS idx_timestamp ON aranet_readings(timestamp);
```

## Database maintenance

The database grows at roughly 1 row per reading (~100 bytes). At 1-minute intervals that's about 15 MB/year.

To manually compact:

```sh
sqlite3 /var/lib/aranet4-dash/aranet.db "VACUUM;"
```

To delete old data (e.g. older than 1 year):

```sh
sqlite3 /var/lib/aranet4-dash/aranet.db "DELETE FROM aranet_readings WHERE timestamp < datetime('now', '-1 year');"
sqlite3 /var/lib/aranet4-dash/aranet.db "VACUUM;"
```

## Troubleshooting

### Device not found during scan

- Make sure the Aranet4 is within Bluetooth range
- Check Bluetooth is up: `sudo systemctl status bluetooth`
- Restart Bluetooth: `sudo systemctl restart bluetooth`
- Make sure the MAC address in `.env` is correct
- Try `uv run aranetctl --scan` to verify the device is visible

### No readings in scan output

- **Smart Home integrations** must be enabled in the Aranet Home phone app — without it the device won't broadcast readings in BLE advertisements

### Cron job not running

```sh
# Check cron is running
sudo systemctl status cron

# Check the log
tail -20 /home/ian/dev/aranet4-dash/cron.log

# Make sure uv is on PATH
which uv
```

### Grafana can't read the database

The DB lives in `/var/lib/aranet4-dash/` which is owned by `ian:grafana`. Check permissions:

```sh
ls -la /var/lib/aranet4-dash/
# Should show: drwxr-x--- ian grafana  (directory)
# and:        -rw-r----- ian grafana  (aranet.db)
```

Fix if needed:

```sh
sudo chown ian:grafana /var/lib/aranet4-dash /var/lib/aranet4-dash/aranet.db
chmod 750 /var/lib/aranet4-dash
chmod 640 /var/lib/aranet4-dash/aranet.db
```
