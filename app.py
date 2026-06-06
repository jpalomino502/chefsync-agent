import sys
import threading
import time

from flask import Flask
from flask_cors import CORS

from config import load_config
from logging_config import setup_logging
from os_support import PlatformSupport
from api.routes import register_routes
from services.lock import acquire_single_instance_lock
from services.tray import run_with_tray
from services.db_poller import start_poller


def create_app(app_config=None, support=None):
    config = app_config or load_config()
    support = support or PlatformSupport()
    app = Flask(__name__)
    # allow_private_network=True makes Flask-CORS respond with
    # "Access-Control-Allow-Private-Network: true" when Chrome sends the PNA
    # preflight from a public HTTPS origin (e.g. dashboard.chefsync.app) to a
    # loopback address (127.0.0.1). Without this flag Flask-CORS defaults to
    # "false" and Chrome blocks every request from production to the agent.
    CORS(
        app,
        resources={r"/*": {"origins": config.cors_origins}},
        allow_private_network=True,
    )
    app.config["APP_CONFIG"] = config
    app.config["SUPPORT"] = support
    register_routes(app)
    return app


def main():
    logger = setup_logging()
    config = load_config()
    support = PlatformSupport()
    try:
        lock_handle = acquire_single_instance_lock(config, support)
    except RuntimeError as exc:
        logger.critical(str(exc))
        sys.exit(1)

    app = create_app(config, support)
    logger.info("Starting on %s - http://%s:%s", support.system, config.host, config.port)
    start_poller(support, logger)  # optional Supabase print-queue bridge
    run_with_tray(app, config, support)
    _ = lock_handle


if __name__ == "__main__":
    main()
