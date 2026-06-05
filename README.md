# ChefSync Agent

Local print agent for ChefSync POS. It discovers printers, receives print jobs over HTTP, prints receipts, and can optionally poll the Supabase print queue.

## What it does

- Detects local printers on Windows, Linux, and macOS.
- Exposes a small HTTP API for health checks, discovery, and printing.
- Supports text, JSON, HTML, and raw ESC/POS jobs.
- Can run headless; the tray icon is optional.

## Repository layout

- `app.py` - application entry point and startup wiring.
- `api/` - HTTP routes and request handlers.
- `services/` - device, health, lock, tray, and polling services.
- `services/printing/` - printer discovery, dispatch, drivers, and ESC/POS helpers.
- `virtual_printer/` - local viewer and test server for print previews.
- `scripts/` - manual or integration helpers.

## Requirements

- Python 3.10 or newer.
- A virtual environment is recommended.
- Optional platform packages:
  - Windows: `pywin32`
  - Linux: `pycups`
  - macOS: no extra backend package is usually required

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The agent listens on `http://127.0.0.1:5321` by default. Override the host and port with `CHEFSYNC_HOST` and `CHEFSYNC_PORT`.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Returns agent health and device metadata. |
| GET | `/printers` | Lists available printers and capabilities. |
| POST | `/print` | Sends a print job to a specific printer. |
| POST | `/print/test` | Prints a test ticket on the default printer or a selected one. |

Supported `format` values: `text`, `json`, `html`, `escpos`.

### Example requests

```bash
curl http://127.0.0.1:5321/health
curl http://127.0.0.1:5321/printers
```

```bash
curl -X POST http://127.0.0.1:5321/print/test \
  -H 'Content-Type: application/json' \
  -d '{"printer_id":"PRINTER_ID"}'
```

## Supabase bridge

If you want the agent to poll pending print jobs from Supabase, set:

```bash
export CHEFSYNC_SUPABASE_URL=https://<project>.supabase.co
export CHEFSYNC_SUPABASE_KEY=<service_role_key>
export CHEFSYNC_LOCATION_ID=<location_uuid>
export CHEFSYNC_POLL_INTERVAL=3
python app.py
```

The agent resolves the printer from `options.printer_name` first, then from `print_devices` using `print_device_id`.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

This project is distributed under the MIT License. See [LICENSE](LICENSE).
