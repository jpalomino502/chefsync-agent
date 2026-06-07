"""Headless runner: starts ONLY the Supabase print-queue poller.

No Flask HTTP server, no tray icon — ideal for servers, CI, Docker, or a quick
local end-to-end test where you just need the agent to claim and print jobs.

Config comes from the usual sources (env wins, then config file) — see
services/agent_config.py. Minimum:
  CHEFSYNC_SUPABASE_URL, CHEFSYNC_SUPABASE_KEY (anon ok), CHEFSYNC_LOCATION_ID

Run:
  CHEFSYNC_SUPABASE_URL=... CHEFSYNC_SUPABASE_KEY=... CHEFSYNC_LOCATION_ID=... \
  .venv/bin/python run_headless.py
"""
import time

from logging_config import setup_logging
from os_support import PlatformSupport
from services.db_poller import start_poller, is_enabled, _config


def main():
    logger = setup_logging()
    support = PlatformSupport()
    cfg = _config()
    logger.info(
        "[headless] url=%s location=%s device=%s interval=%ss sink=%s",
        cfg["url"], (cfg["location_id"] or "")[:8], (cfg["device_id"] or "")[:8],
        cfg["interval"], __import__("os").getenv("CHEFSYNC_PRINT_SINK_DIR", "(default tmp)"),
    )
    if not is_enabled():
        logger.error("[headless] poller NOT enabled — missing url/key/location_id. Aborting.")
        raise SystemExit(1)

    start_poller(support, logger)
    logger.info("[headless] poller running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        logger.info("[headless] stopping.")


if __name__ == "__main__":
    main()
