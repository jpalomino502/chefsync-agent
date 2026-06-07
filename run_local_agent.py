"""Full local agent WITHOUT the tray icon — for local dev / macOS / servers.

Same as `python app.py` (HTTP API on :5321 + Supabase poller + heartbeat +
printer auto-registration) but it does NOT start the pystray tray, which can
hang or fail in a headless / background process on macOS.

What runs:
  • Flask HTTP API  (/health, /printers, /print, /print/test, /config*)
  • print-queue poller (claim_print_job → print → mark_print_job_status)
  • heartbeat (agent_heartbeat) + printer auto-registration (register_print_device)

Use this when you want the dashboard on the SAME machine to also detect the
agent over HTTP. For pure queue printing (tablets, other machines) the poller
alone is enough — see run_headless.py.

Config: env wins, then config file (services/agent_config.py). Minimum:
  CHEFSYNC_SUPABASE_URL, CHEFSYNC_SUPABASE_KEY (anon ok), CHEFSYNC_LOCATION_ID

Run:
  CHEFSYNC_SUPABASE_URL=... CHEFSYNC_SUPABASE_KEY=... CHEFSYNC_LOCATION_ID=... \
  .venv/bin/python run_local_agent.py
"""
from config import load_config
from logging_config import setup_logging
from os_support import PlatformSupport
from app import create_app
from services.db_poller import start_poller, is_enabled, _config


def main():
    logger = setup_logging()
    config = load_config()
    support = PlatformSupport()

    cfg = _config()
    logger.info("[local-agent] http=http://%s:%s  location=%s  device=%s",
                config.host, config.port, (cfg["location_id"] or "")[:8], (cfg["device_id"] or "")[:8])

    app = create_app(config, support)

    if is_enabled():
        start_poller(support, logger)  # poller + heartbeat + printer registration
    else:
        logger.warning("[local-agent] poller DISABLED — set CHEFSYNC_SUPABASE_URL/KEY/LOCATION_ID to enable queue printing")

    logger.info("[local-agent] serving HTTP (no tray). Ctrl+C to stop.")
    # Blocking; poller runs in its own daemon thread. No reloader (would double-run).
    app.run(host=config.host, port=config.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
