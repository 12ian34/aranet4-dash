---
name: raspberry-pi-ble
description: Raspberry Pi deployment for BLE sensor projects. Use when troubleshooting Bluetooth, setting up permissions, configuring systemd/cron, or debugging Pi-specific issues.
---

# Raspberry Pi + BLE deployment

## Bluetooth

- Bluetooth stack: `bluez` (pre-installed on Raspberry Pi OS Bookworm).
- Check status: `sudo systemctl status bluetooth`
- Restart: `sudo systemctl restart bluetooth`
- The `aranet4` Python library uses `bleak` under the hood, which talks to bluez via D-Bus — no extra system packages needed beyond bluez.

## BLE advertisement scan vs GATT connect

- **Advertisement scan** (`find_nearby`): reads broadcast data, no pairing needed. Reliable on Pi.
- **GATT connect** (`get_current_readings`): connects directly to device. Hangs on Linux/bluez for Aranet4 (service discovery never completes). Do not use.

## File permissions for Grafana

The SQLite DB lives in `/var/lib/aranet4-dash/` so Grafana can read it:

```sh
sudo mkdir -p /var/lib/aranet4-dash
sudo chown $USER:grafana /var/lib/aranet4-dash
chmod 750 /var/lib/aranet4-dash
# After first run:
chmod 640 /var/lib/aranet4-dash/aranet.db
```

The `grafana` user reads via group permission. The `-journal` and `-wal` files (if any) also need group read.

## Shell compatibility

- The Pi runs **fish** shell by default (user preference), but all scripts and docs use POSIX-compatible syntax.
- Cron uses `/bin/sh` regardless of user shell.
- `$HOME`, `$USER`, `~` all work in both bash and fish.

## Common issues

- **BLE scan returns nothing**: check "Smart Home integrations" is enabled in Aranet Home app.
- **Permission denied on DB**: check `ls -la /var/lib/aranet4-dash/` — file should be owned by `$USER:grafana`.
- **uv not found in cron**: add `PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin` at top of crontab.
