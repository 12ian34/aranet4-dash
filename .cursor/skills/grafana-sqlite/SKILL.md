---
name: grafana-sqlite
description: Grafana dashboard development with the frser-sqlite-datasource plugin. Use when editing grafana/dashboard.json, writing Grafana SQL queries, or troubleshooting timestamp display issues.
---

# Grafana + SQLite datasource

## Plugin

`frser-sqlite-datasource` — reads `.db` files directly, no intermediate server. Install with `grafana-cli plugins install frser-sqlite-datasource`.

## Timestamp conversion (critical)

The `timestamp` column stores SQLite datetime strings (e.g. `2026-02-09 01:21:11`). The plugin cannot use these directly — it needs numeric Unix epoch values.

### Time series panels (`queryType: "time series"`)

Convert to **seconds** epoch. The column **must** be aliased as `time`:

```sql
SELECT
  CAST(strftime('%s', timestamp) AS INTEGER) AS time,
  co2_ppm
FROM aranet_readings
ORDER BY timestamp
```

### Table/stat/bar gauge panels (`queryType: "table"`)

Convert to **milliseconds** epoch (`* 1000`) for Grafana display units like `dateTimeFromNow`:

```sql
SELECT
  CAST(strftime('%s', timestamp) AS INTEGER) * 1000 AS last_updated,
  co2_ppm, temperature_c, humidity_percent, pressure_hpa, battery_percent
FROM aranet_readings
ORDER BY timestamp DESC
LIMIT 1
```

### Why CAST is required

`strftime('%s', ...)` returns **text** in SQLite. Without `CAST(... AS INTEGER)`, the plugin may misinterpret the value or fail silently.

## Dashboard JSON

- Location: `grafana/dashboard.json`
- Export from Grafana: Dashboard settings > JSON Model > copy, or Share > Export > Save to file
- Import: Dashboards > New > Import > Upload JSON file
- The `uid` field (`"aranet4-dash"`) and datasource UIDs are baked into the JSON — after importing, you may need to update the datasource UID to match your local Grafana instance.

## Panel types in use

| Panel         | Type         | Query type  | Timestamp    |
|---------------|-------------|-------------|--------------|
| Latest Reading| `bargauge`  | `table`     | ms (`* 1000`)|
| CO2           | `timeseries`| `time series`| seconds     |
| Temperature   | `timeseries`| `time series`| seconds     |
| Pressure      | `timeseries`| `time series`| seconds     |
| Humidity      | `timeseries`| `time series`| seconds     |

## Colour conventions

- All time series lines: `#8AB8FF` (light blue)
- Threshold bands: green `#96D98D`, yellow `#FFCB47`, red `#E8837C`
