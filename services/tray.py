import os
import sys
import threading
import time

from logging_config import setup_logging
from resources import resource_path
from services.health import background_health_check


def run_with_tray(app, config, support):
    logger = setup_logging()

    def run_server():
        app.run(host=config.host, port=config.port, debug=False, use_reloader=False)

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
