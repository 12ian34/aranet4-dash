# Aranet4 Bluetooth Data Logger

Read CO2, temperature, humidity, pressure, and battery from an [Aranet4](https://aranet.com/products/aranet4/) sensor over Bluetooth LE and log to a local SQLite database. Visualise with Grafana.

Designed to run on a Raspberry Pi via crontab.

## Prerequisites

- Raspberry Pi (tested on Pi 4 / Pi 5) with Bluetooth
- Raspberry Pi OS (Bookworm or later)
- Python 3.9+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- An Aranet4 sensor within Bluetooth range

All shell commands below work in both bash and fish.

## 1. Clone and install

```sh
cd /home/ian/dev
git clone <repo-url> aranet4-dash
cd aranet4-dash
uv sync
```

That's it — `uv sync` creates the venv and installs dependencies from `pyproject.toml`.

## 2. Find and pair your Aranet4

Make sure the Aranet4 is nearby and not connected to a phone. Also enable **Smart Home integrations** in the Aranet Home phone app (device settings) — this is required for BLE data access.

```sh
bluetoothctl
```

Inside `bluetoothctl`:

```
scan on
```

Wait for a line like:

```
[NEW] Device AA:BB:CC:DD:EE:FF Aranet4 ABCDE
```

Note the MAC address, then pair and trust:

```
scan off
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
exit
```

## 3. Configure

Copy the example and fill in your values:

```sh
cp .env.example .env
nano .env
```

```env
ARANET_MAC=AA:BB:CC:DD:EE:FF
DB_PATH=/home/ian/dev/aranet4-dash/aranet.db
POLL_INTERVAL=60
```

- `ARANET_MAC` — the MAC address from step 2
- `DB_PATH` — where to store the SQLite database (directory will be created if needed)
- `POLL_INTERVAL` — seconds between readings in daemon mode (default 60, not used by crontab)

## 4. Test a single reading

```sh
cd /home/ian/dev/aranet4-dash
uv run aranet_logger.py --single
```

You should see output like:

```
2026-02-09 12:00:00 INFO Reading from Aranet4 (AA:BB:CC:DD:EE:FF)...
2026-02-09 12:00:00 INFO CO2=847 ppm  Temp=21.3°C  Humidity=45%  Pressure=1013.2 hPa  Battery=91%
2026-02-09 12:00:00 INFO Reading saved to database
```

## 5. Verify the database

```sh
sqlite3 /home/ian/dev/aranet4-dash/aranet.db
```

```sql
SELECT * FROM aranet_readings ORDER BY timestamp DESC LIMIT 5;
.quit
```

## 6. Set up crontab

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

## 7. Install Grafana

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

## 8. Install the SQLite datasource plugin

```sh
sudo grafana-cli plugins install frser-sqlite-datasource
sudo systemctl restart grafana-server
```

## 9. Configure the datasource

1. Open Grafana at `http://<pi-ip>:3000`
2. Go to **Connections > Data sources > Add data source**
3. Search for **SQLite**
4. Set the path to:
   ```
   /home/ian/dev/aranet4-dash/aranet.db
   ```
5. Click **Save & test** — should say "Data source is working"

## 10. Create a dashboard

Create a new dashboard and add panels. Here are some example queries:

**CO2 over time:**

```sql
SELECT
  timestamp AS time,
  co2_ppm
FROM aranet_readings
WHERE timestamp >= datetime('now', '-24 hours')
ORDER BY timestamp
```

**Temperature over time:**

```sql
SELECT
  timestamp AS time,
  temperature_c
FROM aranet_readings
WHERE timestamp >= datetime('now', '-24 hours')
ORDER BY timestamp
```

**Humidity over time:**

```sql
SELECT
  timestamp AS time,
  humidity_percent
FROM aranet_readings
WHERE timestamp >= datetime('now', '-24 hours')
ORDER BY timestamp
```

**Pressure over time:**

```sql
SELECT
  timestamp AS time,
  pressure_hpa
FROM aranet_readings
WHERE timestamp >= datetime('now', '-24 hours')
ORDER BY timestamp
```

**Latest reading (stat panel):**

```sql
SELECT co2_ppm, temperature_c, humidity_percent, pressure_hpa, battery_percent
FROM aranet_readings
ORDER BY timestamp DESC
LIMIT 1
```

**Tips:**
- Set each panel's time column to `time` in the query options
- Use "Time series" visualisation for the line charts
- Use "Stat" visualisation for the latest reading
- Set thresholds on CO2: green < 800, yellow < 1000, red >= 1000
- Set the dashboard auto-refresh to 1m to match the polling interval

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
sqlite3 /home/ian/dev/aranet4-dash/aranet.db "VACUUM;"
```

To delete old data (e.g. older than 1 year):

```sh
sqlite3 /home/ian/dev/aranet4-dash/aranet.db "DELETE FROM aranet_readings WHERE timestamp < datetime('now', '-1 year');"
sqlite3 /home/ian/dev/aranet4-dash/aranet.db "VACUUM;"
```

## Troubleshooting

### Bluetooth connection fails

- Make sure the Aranet4 isn't connected to a phone (it only supports one connection at a time)
- Check Bluetooth is up: `sudo systemctl status bluetooth`
- Restart Bluetooth: `sudo systemctl restart bluetooth`
- Make sure the MAC address in `.env` is correct

### Readings not working

- Make sure the device is **paired** (`bluetoothctl pair AA:BB:CC:DD:EE:FF`)
- Make sure **Smart Home integrations** is enabled in the Aranet Home phone app
- Enable debug logging — temporarily change `level=logging.INFO` to `level=logging.DEBUG` in `setup_logging()` and run `uv run aranet_logger.py --single`

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

The Grafana process (`grafana` user) needs read access to the `.db` file:

```sh
chmod 644 /home/ian/dev/aranet4-dash/aranet.db
```

If writes are also blocked, check the directory permissions too:

```sh
chmod 755 /home/ian/dev/aranet4-dash
```
