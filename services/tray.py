import os
import sys
import threading
import time

from logging_config import setup_logging
from resources import resource_path
from services.health import background_health_check


def _ssl_context(config):
    """Return an ssl_context for Flask, or None to run plain HTTP.

    Priority:
      1. CHEFSYNC_SSL_CERT + CHEFSYNC_SSL_KEY env vars  (mkcert certs)
      2. config.ssl_cert + config.ssl_key               (from config file)
      3. None → plain HTTP

    To use:
      mkcert localhost 127.0.0.1 ::1
      CHEFSYNC_SSL_CERT=ssl/localhost+2.pem CHEFSYNC_SSL_KEY=ssl/localhost+2-key.pem python3 app.py
    """
    cert = os.getenv("CHEFSYNC_SSL_CERT") or getattr(config, "ssl_cert", None)
    key = os.getenv("CHEFSYNC_SSL_KEY") or getattr(config, "ssl_key", None)
    if cert and key:
        if os.path.isfile(cert) and os.path.isfile(key):
            logger = setup_logging()
            logger.info("[ssl] HTTPS enabled — cert=%s", cert)
            import ssl
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            return ctx
        else:
            setup_logging().warning("[ssl] cert/key not found: %s / %s — falling back to HTTP", cert, key)
    return None


def run_with_tray(app, config, support):
    logger = setup_logging()

    def run_server():
        ssl_ctx = _ssl_context(config)
        app.run(
            host=config.host, port=config.port,
            debug=False, use_reloader=False,
            ssl_context=ssl_ctx,
        )

    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(
        target=background_health_check,
        args=(config.host, config.port, config.health_interval_sec, logger),
        daemon=True,
    ).start()

    if support.pystray:
        try:
            from PIL import Image

            icon_img = _load_icon(Image, config)
            menu = support.pystray["Menu"](
                support.pystray["MenuItem"]("Exit", lambda icon, item: _exit(icon))
            )
            icon = support.pystray["Icon"]("ChefsyncAgent", icon_img, "Local Print Server", menu)
            icon.run()
            return
        except Exception as exc:
            logger.error("pystray failed: %s", exc)

    logger.info("No tray available. Press CTRL+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sys.exit(0)


def _load_icon(Image, config):
    try:
        return Image.open(resource_path(config.icon_path))
    except Exception:
        return Image.new("RGB", (64, 64), "blue")


def _exit(icon):
    try:
        icon.stop()
    finally:
        os._exit(0)
