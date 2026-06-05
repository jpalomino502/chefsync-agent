"""Supabase print-queue bridge for chefsync-agent.

Claims pending print_jobs for this agent's location via claim_print_job
(FOR UPDATE SKIP LOCKED, so two agents never grab the same job), prints them
through the local dispatcher, and reports the outcome via mark_print_job_status.

Environment:
  CHEFSYNC_SUPABASE_URL          https://<project>.supabase.co
  CHEFSYNC_SUPABASE_KEY          service_role key  (LOCAL/SERVER ONLY — never ship to a browser)
  CHEFSYNC_LOCATION_ID           location uuid this agent prints for
  CHEFSYNC_AGENT_DEVICE_ID       (optional) override the persisted device id
  CHEFSYNC_AGENT_POLL_INTERVAL_MS (optional) poll interval in ms (default 3000)

claim_print_job / mark_print_job_status are GRANTed to service_role, so the
service-role key is required (the RPCs need to bypass RLS and run for any
business at this location). Keep the key on the machine running the agent only.
"""
import os
import threading
import time

import requests

from services.device import get_device_id


def _config():
    interval_ms = os.getenv("CHEFSYNC_AGENT_POLL_INTERVAL_MS")
    if interval_ms:
        interval = max(0.5, int(interval_ms) / 1000.0)
    else:
        interval = float(os.getenv("CHEFSYNC_POLL_INTERVAL", "3"))
    return {
        "url": os.getenv("CHEFSYNC_SUPABASE_URL", "").rstrip("/"),
        "key": os.getenv("CHEFSYNC_SUPABASE_KEY", ""),
        "location_id": os.getenv("CHEFSYNC_LOCATION_ID", ""),
        "device_id": os.getenv("CHEFSYNC_AGENT_DEVICE_ID") or get_device_id(),
        "interval": interval,
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


def _poll_loop(support, logger):
    cfg = _config()
    logger.info("[poller] started location=%s device=%s interval=%ss", cfg["location_id"][:8], cfg["device_id"][:8], cfg["interval"])
    while True:
        try:
            status, job_id = process_one_job(support, logger)
            if status is None:
                time.sleep(cfg["interval"])  # queue empty -> wait
            # else: loop immediately to drain the queue
        except Exception as exc:
            logger.warning("[poller] loop error: %s", exc)
            time.sleep(cfg["interval"])


def start_poller(support, logger):
    """Start the poll loop in a daemon thread if configured. Returns True if started."""
    if not is_enabled():
        logger.info("[poller] disabled (set CHEFSYNC_SUPABASE_URL/KEY/LOCATION_ID to enable)")
        return False
    threading.Thread(target=_poll_loop, args=(support, logger), daemon=True).start()
    return True
