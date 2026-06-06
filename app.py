import sys
from typing import Any, Optional, List

from flask import Flask, request, make_response

from config import load_config
from logging_config import setup_logging
from os_support import PlatformSupport
from api.routes import register_routes
from services.lock import acquire_single_instance_lock
from services.tray import run_with_tray
from services.db_poller import start_poller

# ---------------------------------------------------------------------------
# Manual CORS + Private Network Access middleware
#
# Why not Flask-CORS?
#   Flask-CORS 6.x adds "Access-Control-Allow-Private-Network: true/false" only
#   on OPTIONS preflights (not on actual GET/POST responses), and its default is
#   "false". Chrome's PNA spec requires "true" in the preflight response; some
#   Chrome versions also check the actual response. Rolling our own gives us
#   full control over every header on every response.
#
# Chrome Private Network Access (PNA):
#   When https://dashboard.chefsync.app fetches http://127.0.0.1:5321, Chrome
#   treats 127.0.0.1 as "loopback / private network" and sends a preflight:
#     Access-Control-Request-Private-Network: true
#   The server MUST respond:
#     Access-Control-Allow-Private-Network: true
#   We include this header on ALL responses (OPTIONS + GET/POST) to be safe.
# ---------------------------------------------------------------------------


def _reflect_origin(origin, allowed):
    # type: (str, List[str]) -> Optional[str]
    """Return the origin to reflect, or None if not in the allow-list."""
    if "*" in allowed:
        return origin or "*"
    return origin if origin in allowed else None


def _add_cors(response, origin, allowed):
    # type: (Any, str, List[str]) -> None
    """Inject CORS + PNA headers into *response* (mutates in place)."""
    reflected = _reflect_origin(origin, allowed)
    if not reflected:
        return
    h = response.headers
    h["Access-Control-Allow-Origin"] = reflected
    h["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    h["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    # Required by Chrome PNA — must be present on OPTIONS *and* actual responses
    h["Access-Control-Allow-Private-Network"] = "true"
    h["Vary"] = "Origin"


def create_app(app_config=None, support=None):
    config = app_config or load_config()
    support = support or PlatformSupport()
    allowed = config.cors_origins  # list of explicit origins (or ["*"])

    app = Flask(__name__)

    @app.before_request
    def handle_preflight():
        """Intercept OPTIONS preflights and return immediately with full headers.

        Chrome sends a preflight before every cross-origin request that targets
        a private/loopback address. We must respond 204 with the PNA header or
        Chrome blocks the subsequent GET/POST.
        """
        if request.method != "OPTIONS":
            return None
        origin = request.headers.get("Origin", "")
        resp = make_response("", 204)
        _add_cors(resp, origin, allowed)
        # Preflight-only: tell Chrome it may cache this answer for 2 h
        resp.headers["Access-Control-Max-Age"] = "7200"
        return resp

    @app.after_request
    def add_cors_to_response(response):
        """Add CORS + PNA headers to every non-preflight response.

        Browsers check Access-Control-Allow-Origin on the actual GET/POST as
        well as on the preflight. Access-Control-Allow-Private-Network is
        included here too for Chrome versions that inspect actual responses.
        """
        origin = request.headers.get("Origin", "")
        _add_cors(response, origin, allowed)
        return response

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
