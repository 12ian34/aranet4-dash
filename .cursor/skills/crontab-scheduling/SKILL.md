---
name: crontab-scheduling
description: Crontab setup for periodic script execution on Linux. Use when configuring cron jobs, debugging cron issues, or setting up scheduled tasks.
---

# Crontab scheduling

## Setup for this project

```cron
PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin

* * * * * cd $HOME/dev/aranet4-dash && uv run aranet_logger.py --single >> $HOME/dev/aranet4-dash/cron.log 2>&1
```

## Key points

- **PATH**: cron starts with a minimal PATH. Set it at the top of crontab so `uv` is found.
- **`$HOME`**: cron sets `HOME` automatically — use `$HOME` (not `~`) in crontab lines since tilde expansion is shell-specific.
- **`cd` first**: the script resolves `.env` relative to its own directory, but `cd` ensures any relative paths in the command work too.
- **`--single` mode**: one reading per invocation, then exit. Cron handles the scheduling. Simpler than a long-running daemon.
- **Logging**: `>> cron.log 2>&1` appends both stdout and stderr. The script logs to stdout via `logging`.

## Debugging

```sh
# Verify crontab is saved
crontab -l

# Check cron service
sudo systemctl status cron

# Watch the log
tail -f ~/dev/aranet4-dash/cron.log

# Test the exact command cron would run
cd ~/dev/aranet4-dash && uv run aranet_logger.py --single
```

## Concurrency protection

Cron does **not** wait for the previous invocation to finish. If a run takes longer than 1 minute (e.g. BLE scan hangs, D-Bus stalls), the next cron invocation starts in parallel. This cascades:

1. Stuck process holds the BLE adapter via D-Bus
2. Next invocation can't scan — also gets stuck
3. Processes pile up every minute, all holding D-Bus connections
4. Eventually dozens of zombie processes permanently block BLE scanning

**Fix**: `aranet_logger.py` uses `fcntl.flock()` in `single_reading()` with `LOCK_NB` (non-blocking). If another instance is already running, it logs a warning and exits immediately with code 0. The lock file is `/tmp/aranet4-dash.lock`.

**Diagnosing pile-ups**: `ps aux | grep aranet_logger` — if you see multiple processes with old start dates, kill them all with `pkill -f 'aranet_logger.py --single'` and restart the Bluetooth stack with `sudo systemctl restart bluetooth`.

## Timing

- `* * * * *` = every minute.
- At 1-minute intervals, the DB grows ~15 MB/year.
- The BLE scan (`duration=10`) plus DB write takes ~10-12 seconds per invocation, well within the 1-minute window.
