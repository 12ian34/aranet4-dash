# Aranet4 Bluetooth Data Logger

Read CO2, temperature, humidity, pressure, and battery from an [Aranet4](https://aranet.com/products/aranet4/) sensor over Bluetooth LE and log to a local SQLite database. Visualise with Grafana.

Designed to run on a Raspberry Pi via crontab.

## Prerequisites

- Raspberry Pi (tested on Pi 4 / Pi 5) with Bluetooth
- Raspberry Pi OS (Bookworm or later)
- Bluetooth enabled and running (`sudo systemctl status bluetooth`)
- Python 3.9+ (pre-installed on Bookworm)
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- [Grafana](https://grafana.com/docs/grafana/latest/setup-grafana/installation/debian/) + [SQLite datasource plugin](https://github.com/fr-ser/grafana-sqlite-datasource) (installed in steps 8-9 below)
- An Aranet4 sensor within Bluetooth range
- **Smart Home integrations** enabled in the [Aranet Home](https://aranet.com/aranet-home-app) phone app (device settings) — required for BLE data access

All shell commands below work in both bash and fish.

## 1. Clone and install

```sh
git clone https://github.com/12ian34/aranet4-dash.git
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
sudo chown $USER:grafana /var/lib/aranet4-dash
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
cd ~/dev/aranet4-dash    # or wherever you cloned the repo
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

Add these lines to poll every minute. The `sleep 30` staggers the BLE scan from other jobs that fire at the top of the minute (BlueZ allows only one active LE scan at a time).

```cron
PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin

* * * * * /usr/bin/sleep 30 && cd $HOME/dev/aranet4-dash && uv run aranet_logger.py --single >> $HOME/dev/aranet4-dash/cron.log 2>&1
```

The `PATH` line ensures cron can find `uv`. Save and exit, then verify:

```sh
crontab -l
```

After `git pull` on the Pi, re-open `crontab -e` and update this line if it changed in the repo — git does not sync crontab for you.

Check it's working after a few minutes:

```sh
tail -f ~/dev/aranet4-dash/cron.log
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

- **Bar gauge** — latest reading for CO2, Temperature, Humidity, Pressure, Battery with colour-coded thresholds, plus a "Last Updated" relative timestamp
- **CO2 time series** — with green/yellow/red threshold bands at 800/1000 ppm
- **Temperature time series** — blue line with comfort-zone threshold bands, 10-35 C range
- **Humidity time series** — blue line with threshold bands, 0-100% range
- **Pressure time series** — blue line, 950-1050 hPa range

> **Note:** The `timestamp` column stores SQLite datetime strings, but the SQLite datasource plugin needs numeric Unix epoch values. Time series queries convert with `CAST(strftime('%s', timestamp) AS INTEGER)` (seconds). The bar gauge "Last Updated" field uses `* 1000` (milliseconds) so Grafana's `dateTimeFromNow` unit can display relative time like "5 min ago".

## 12. (Optional) Alerts via ntfy

Grafana can ping your phone via [ntfy](https://ntfy.sh) when the logger stops producing readings — typically a wedged BLE controller (see Troubleshooting). Provisioning YAML lives at [grafana/provisioning/alerting/](grafana/provisioning/alerting/).

**a) Subscribe to the topic on your phone.** Install the ntfy app, add topic `ian-aranet-down` (or whatever you chose — match `url:` in `contactpoints.yaml`). If the topic requires auth, sign in with the same ntfy account whose token you'll use below.

**b) Put the ntfy token where Grafana can read it.** Grafana's systemd service reads `/etc/default/grafana-server`. Append:

```sh
sudo sh -c 'echo "NTFY_TOKEN=tk_your_token_here" >> /etc/default/grafana-server'
```

Keep the file `root`-owned and `640` — it holds a secret.

**c) Deploy the YAML.** Grafana auto-loads anything in `/etc/grafana/provisioning/alerting/`:

```sh
sudo cp grafana/provisioning/alerting/*.yaml /etc/grafana/provisioning/alerting/
sudo chown root:grafana /etc/grafana/provisioning/alerting/*.yaml
sudo chmod 640 /etc/grafana/provisioning/alerting/*.yaml
sudo systemctl restart grafana-server
```

**d) Verify.** Open Grafana → **Alerting > Alert rules**. You should see `Aranet4 readings stale` in the `Aranet4` folder. **Contact points** should list `ntfy`. Hit **Test** on the contact point — a test notification should land on your phone.

**What triggers / how often you're pinged:**

- Alert fires when `seconds_since_last > 300` (5 min) for at least 1 minute.
- Fires once immediately, then re-sends every `repeat_interval: 1h` while still firing.
- Sends a resolved notification the moment a new reading lands.

Tune thresholds in [rules.yaml](grafana/provisioning/alerting/rules.yaml) (`params: [300]`) or cadence in [policies.yaml](grafana/provisioning/alerting/policies.yaml) (`repeat_interval`) and restart Grafana.

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

### `InProgress` / `Opcode 0x200c failed: -16`

If **`bluetoothctl scan on`** prints **`Failed to start discovery: org.bluez.Error.InProgress`** and **`dmesg | grep -i hci`** shows lines like **`Opcode 0x200c failed: -16`** / **`Unable to disable scanning`**, the kernel's hci0 state thinks scanning is already enabled. `systemctl restart bluetooth` only bounces the userspace daemon — that state survives and `InProgress` keeps coming back.

**Recover from userspace** (no reboot):

```sh
sudo rfkill block bluetooth; sleep 2; sudo rfkill unblock bluetooth
```

Blocking/unblocking the radio brings the HCI device down and up, which clears the stuck "scanning enabled" flag. `aranet_logger.py` does this automatically on `InProgress` — for that to work from cron, add a no-password sudoers entry:

```sh
sudo visudo -f /etc/sudoers.d/aranet4-dash
```

```sudoers
ian ALL=(ALL) NOPASSWD: /usr/sbin/rfkill
```

(Adjust the username to match the cron user. The old `systemctl restart bluetooth` entry can be removed — the logger no longer uses it.)

**Likely causes of the wedge** (worth eliminating if it recurs):

- A scan enabled LE scanning but the process died before disabling it. Next call → `EBUSY`. `rfkill` cycle recovers.
- Another BLE consumer (a paired device with auto-connect, a stray `bluetoothctl scan on`, another Python/bleak process) is racing the logger's scan. Check: `bluetoothctl paired-devices`, `ps aux | grep -E 'bluetoothctl|aranet|bleak'`. Advertisement reads do **not** need pairing — `bluetoothctl remove <MAC>` if the Aranet is paired.

**If `rfkill` doesn't clear it:** rare, but the controller firmware itself can wedge. Then reboot (`sudo reboot`).

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
tail -20 ~/dev/aranet4-dash/cron.log

# Make sure uv is on PATH
which uv
```

### Grafana can't read the database

The DB lives in `/var/lib/aranet4-dash/` which should be owned by `<your-user>:grafana`. Check permissions:

```sh
ls -la /var/lib/aranet4-dash/
# Should show: drwxr-x--- <user> grafana  (directory)
# and:        -rw-r----- <user> grafana  (aranet.db)
```

Fix if needed:

```sh
sudo chown $USER:grafana /var/lib/aranet4-dash /var/lib/aranet4-dash/aranet.db
chmod 750 /var/lib/aranet4-dash
chmod 640 /var/lib/aranet4-dash/aranet.db
```
