"""Supabase print-queue bridge for chefsync-agent.

Claims pending print_jobs for this agent's location via claim_print_job
(FOR UPDATE SKIP LOCKED, so two agents never grab the same job), prints them
through the local dispatcher, and reports the outcome via mark_print_job_status.

Configuration (highest priority first):
  1. Environment variables: CHEFSYNC_SUPABASE_URL, CHEFSYNC_SUPABASE_KEY,
     CHEFSYNC_LOCATION_ID, CHEFSYNC_AGENT_DEVICE_ID, CHEFSYNC_AGENT_POLL_INTERVAL_MS
  2. Config file (see agent_config.py for search paths)

The anon key (NEXT_PUBLIC_SUPABASE_ANON_KEY) is sufficient — see
10_agent_anon_grants.sql which grants claim_print_job / mark_print_job_status
to the anon role. Keep the key on the agent machine only.
"""
import threading
import time
from typing import Optional

import requests

from services.device import get_device_id
from services.agent_config import load_file_config, resolve, config_search_paths

# ---------------------------------------------------------------------------
# Global poller state — modified only under _poller_lock
# ---------------------------------------------------------------------------
_poller_lock = threading.Lock()
_poller_stop_event = threading.Event()
_poller_stop_event.set()  # starts as "stopped"
_poller_thread: Optional[threading.Thread] = None

# How often (seconds) the loop runs recover_stuck_jobs as a self-heal step
_RECOVERY_INTERVAL_SEC = 300  # 5 minutes

# How often (seconds) the agent publishes its presence (online + printers) so
# the dashboard can show which agent is alive. Must be well under the frontend's
# "online" threshold (~30s) so a healthy agent never flickers offline.
_HEARTBEAT_INTERVAL_SEC = 15


def _config():
    fc = load_file_config()
    url = resolve(["CHEFSYNC_SUPABASE_URL"], ["supabase_url", "url"], fc).rstrip("/")
    key = resolve(["CHEFSYNC_SUPABASE_KEY"], ["supabase_key", "service_role_key", "key"], fc)
    location_id = resolve(["CHEFSYNC_LOCATION_ID"], ["location_id"], fc)
    device_id = resolve(["CHEFSYNC_AGENT_DEVICE_ID"], ["device_id", "agent_device_id"], fc) or get_device_id()
    interval_ms = resolve(["CHEFSYNC_AGENT_POLL_INTERVAL_MS"], ["poll_interval_ms"], fc)
    if interval_ms:
        interval = max(0.5, int(interval_ms) / 1000.0)
    else:
        interval = float(resolve(["CHEFSYNC_POLL_INTERVAL"], ["poll_interval"], fc, "3"))
    return {
        "url": url,
        "key": key,
        "location_id": location_id,
        "device_id": device_id,
        "interval": interval,
        "source": fc.get("__source__"),
    }


def is_enabled():
    cfg = _config()
    return bool(cfg["url"] and cfg["key"] and cfg["location_id"])


def _headers(key):
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _rpc(cfg, name, body):
    resp = requests.post(f"{cfg['url']}/rest/v1/rpc/{name}", json=body, headers=_headers(cfg["key"]), timeout=10)
    resp.raise_for_status()
    text = (resp.text or "").strip()
    if text in ("", "null"):
        return None
    data = resp.json()
    # composite-returning RPCs may come back as a one-element array
    if isinstance(data, list):
        return data[0] if data else None
    return data


def claim_job(cfg):
    # claim_print_job RETURNS print_jobs (composite). When the queue is empty it
    # RETURNs NULL, which PostgREST serializes as a row of all-NULL columns
    # (not JSON null), so guard on the id.
    job = _rpc(cfg, "claim_print_job", {"p_location_id": cfg["location_id"], "p_device_id": cfg["device_id"]})
    if not job or job.get("id") is None:
        return None
    return job


def mark_status(cfg, job_id, status, error=None):
    return _rpc(cfg, "mark_print_job_status", {
        "p_job_id": job_id, "p_status": status, "p_device_id": cfg["device_id"], "p_error": error,
    })


def recover_stuck_jobs(cfg, logger, stuck_minutes=10):
    """Reset print_jobs stuck in 'printing' for longer than stuck_minutes.

    Called on poller startup and periodically in the loop to self-heal after
    crashes between claim and mark.
    """
    try:
        count = _rpc(cfg, "recover_stuck_print_jobs", {
            "p_location_id": cfg["location_id"],
            "p_stuck_minutes": stuck_minutes,
        })
        if count and int(count) > 0:
            logger.warning("[poller] recovered %d stuck job(s) at location %s", int(count), cfg["location_id"][:8])
    except Exception as exc:
        logger.debug("[poller] recover_stuck_jobs: %s", exc)


def send_heartbeat(cfg, support, logger):
    """Publish this agent's presence + discovered printers via agent_heartbeat.

    Best-effort: a heartbeat failure must never stop the print loop.
    """
    try:
        import platform
        import socket
        from services.printing.devices import discover_devices

        try:
            printers = discover_devices(support)
        except Exception:
            printers = []
        meta = {
            "hostname": socket.gethostname(),
            "platform": getattr(support, "system", platform.system()),
            "agent_version": "1.0.0",
        }
        _rpc(cfg, "agent_heartbeat", {
            "p_location_id": cfg["location_id"],
            "p_device_id": cfg["device_id"],
            "p_printers": printers,
            "p_meta": meta,
        })
        logger.debug("[poller] heartbeat sent (%d printer(s))", len(printers))
    except Exception as exc:
        logger.debug("[poller] heartbeat failed: %s", exc)


def resolve_printer(cfg, job):
    """Resolve the local printer name for a claimed job."""
    options = job.get("options") or {}
    payload = job.get("payload") or {}
    name = options.get("printer_name") or payload.get("printer_name")
    if name:
        return name
    device_id = job.get("print_device_id")
    if device_id:
        try:
            resp = requests.get(
                f"{cfg['url']}/rest/v1/print_devices",
                params={"id": f"eq.{device_id}", "select": "printer_ref,name"},
                headers=_headers(cfg["key"]), timeout=10,
            )
            rows = resp.json() if resp.ok else []
            if rows:
                return rows[0].get("printer_ref") or rows[0].get("name")
        except Exception:
            pass
    return None


def process_one_job(support, logger):
    """Claim + print + mark a single job.

    Returns (final_status, job_id):
      - ("done", id)             printed OK
      - ("failed"|"pending", id) print failed (RPC requeues to 'pending' until
                                 max_attempts, then stays 'failed')
      - (None, None)             queue empty
    """
    cfg = _config()
    job = claim_job(cfg)
    if not job:
        return (None, None)

    job_id = job.get("id")
    attempts = job.get("attempts")
    logger.info("[poller] claimed job %s type=%s format=%s attempt=%s", job_id, job.get("type"), job.get("format"), attempts)

    try:
        from services.printing.dispatch import print_job
        printer = resolve_printer(cfg, job)
        if not printer:
            raise RuntimeError("no printer resolved (set options.printer_name or print_devices.printer_ref)")
        print_job(support, printer, job.get("type"), job.get("format"), job.get("payload"), job.get("options"))
        marked = mark_status(cfg, job_id, "done")
        final = (marked or {}).get("status", "done")
        logger.info("[poller] job %s -> %s on '%s'", job_id, final, printer)
        return (final, job_id)
    except Exception as exc:
        marked = mark_status(cfg, job_id, "failed", error=str(exc))
        final = (marked or {}).get("status", "failed")  # 'pending' if requeued
        logger.error("[poller] job %s FAILED (%s) -> %s", job_id, exc, final)
        return (final, job_id)


def _poll_loop(support, logger, stop_event: threading.Event):
    cfg = _config()
    logger.info(
        "[poller] started location=%s device=%s interval=%ss",
        cfg["location_id"][:8], cfg["device_id"][:8], cfg["interval"],
    )

    # Self-heal: reset any jobs that were stuck from a previous crash
    recover_stuck_jobs(cfg, logger)
    last_recovery = time.monotonic()

    # Announce presence immediately so the dashboard shows the agent online
    send_heartbeat(cfg, support, logger)
    last_heartbeat = time.monotonic()

    while not stop_event.is_set():
        try:
            status, job_id = process_one_job(support, logger)
            if status is None:
                # Queue empty: interruptible sleep (wakes immediately if stopped)
                stop_event.wait(timeout=cfg["interval"])
            # else: drain the queue without sleeping

            # Periodic presence heartbeat
            if time.monotonic() - last_heartbeat > _HEARTBEAT_INTERVAL_SEC:
                send_heartbeat(cfg, support, logger)
                last_heartbeat = time.monotonic()

            # Periodic recovery check
            if time.monotonic() - last_recovery > _RECOVERY_INTERVAL_SEC:
                cfg = _config()  # re-read in case config was updated
                recover_stuck_jobs(cfg, logger)
                last_recovery = time.monotonic()

        except Exception as exc:
            logger.warning("[poller] loop error: %s", exc)
            stop_event.wait(timeout=cfg["interval"])

    logger.info("[poller] stopped")


# ---------------------------------------------------------------------------
# Public lifecycle API
# ---------------------------------------------------------------------------

def start_poller(support, logger) -> bool:
    """Start the poll loop in a daemon thread if configured. Returns True if started."""
    global _poller_stop_event, _poller_thread

    cfg = _config()
    if not is_enabled():
        missing = [n for n, v in (("supabase_url", cfg["url"]), ("supabase_key", cfg["key"]), ("location_id", cfg["location_id"])) if not v]
        logger.warning("[poller] DISABLED — missing: %s", ", ".join(missing))
        logger.warning("[poller] set env CHEFSYNC_SUPABASE_URL/KEY/LOCATION_ID, or create a config file at one of:")
        for p in config_search_paths():
            logger.warning("[poller]   - %s", p)
        logger.warning('[poller] example: {"supabase_url":"https://<proj>.supabase.co","supabase_key":"<anon_key>","location_id":"<uuid>"}')
        return False

    with _poller_lock:
        _poller_stop_event = threading.Event()
        t = threading.Thread(target=_poll_loop, args=(support, logger, _poller_stop_event), daemon=True)
        _poller_thread = t

    logger.info(
        "[poller] ENABLED via %s — location=%s device=%s",
        cfg.get("source") or "environment", cfg["location_id"][:8], cfg["device_id"][:8],
    )
    t.start()
    return True


def stop_poller(timeout=5.0) -> bool:
    """Signal the poller to stop and wait up to `timeout` seconds. Returns True if stopped."""
    global _poller_stop_event, _poller_thread
    with _poller_lock:
        event = _poller_stop_event
        thread = _poller_thread

    if event:
        event.set()
    if thread and thread.is_alive():
        thread.join(timeout=timeout)
        return not thread.is_alive()
    return True


def restart_poller(support, logger) -> bool:
    """Stop any running poller, reload config from disk/env, and start fresh.

    Returns True if the new poller started successfully.
    Called by POST /configure after saving new config to disk.
    """
    stop_poller()
    return start_poller(support, logger)


def poller_status() -> dict:
    """Return current poller state for /config/status."""
    with _poller_lock:
        event = _poller_stop_event
        thread = _poller_thread
    running = bool(thread and thread.is_alive() and event and not event.is_set())
    return {"running": running}
