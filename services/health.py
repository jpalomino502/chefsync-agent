import time
import requests


def background_health_check(host, port, interval_sec, logger):
    url = f"http://{host}:{port}/impresoras"
    while True:
        try:
            res = requests.get(url, timeout=2)
            logger.info("Health OK" if res.ok else "Health FAIL")
        except Exception:
            logger.warning("Server not responding")
        time.sleep(interval_sec)
