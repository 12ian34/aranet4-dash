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

## Timing

- `* * * * *` = every minute.
- At 1-minute intervals, the DB grows ~15 MB/year.
- The BLE scan (`duration=10`) plus DB write takes ~10-12 seconds per invocation, well within the 1-minute window.
