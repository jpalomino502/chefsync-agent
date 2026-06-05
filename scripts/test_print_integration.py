"""Real print_jobs -> agent integration test against the live Supabase DB.

Drives the ACTUAL db_poller (claim_print_job / dispatch / mark_print_job_status)
end to end. Uses the service-role key for the poller (as the real agent does)
and a throwaway authenticated user to set up a business/location and enqueue.

Run (from chefsync-agent/, with creds exported):
  SUPABASE_URL=...  SUPABASE_ANON_KEY=...  SUPABASE_SERVICE_ROLE_KEY=...  \
  ./.venv/bin/python scripts/test_print_integration.py
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from os_support import PlatformSupport  # noqa: E402
from services import db_poller  # noqa: E402

URL = (os.getenv("SUPABASE_URL") or os.getenv("CHEFSYNC_SUPABASE_URL") or "").rstrip("/")
ANON = os.getenv("SUPABASE_ANON_KEY") or os.getenv("CHEFSYNC_SUPABASE_ANON_KEY")
SERVICE = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("CHEFSYNC_SUPABASE_KEY")
if not (URL and ANON and SERVICE):
    print("Missing SUPABASE_URL / SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("test")
support = PlatformSupport()

fails = []
def check(name, cond, extra=""):
    print(f"{'✅' if cond else '❌'} {name}{(' — ' + extra) if extra else ''}")
    if not cond:
        fails.append(name)

def svc_headers():
    return {"apikey": SERVICE, "Authorization": f"Bearer {SERVICE}", "Content-Type": "application/json"}

def admin_create_user(tag):
    email = f"print-smoke+{tag}-{int(time.time()*1000)}@example.com"
    password = "Pr1nt!Test-abc123"
    r = requests.post(f"{URL}/auth/v1/admin/users", headers=svc_headers(),
                      json={"email": email, "password": password, "email_confirm": True,
                            "user_metadata": {"full_name": f"Print {tag}"}}, timeout=15)
    r.raise_for_status()
    uid = r.json()["id"]
    r2 = requests.post(f"{URL}/auth/v1/token?grant_type=password",
                       headers={"apikey": ANON, "Content-Type": "application/json"},
                       json={"email": email, "password": password}, timeout=15)
    r2.raise_for_status()
    return uid, r2.json()["access_token"]

def user_rpc(token, fn, body):
    r = requests.post(f"{URL}/rest/v1/rpc/{fn}",
                      headers={"apikey": ANON, "Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                      json=body, timeout=15)
    if not r.ok:
        raise RuntimeError(f"{fn} -> {r.status_code} {r.text}")
    return r.json() if r.text.strip() not in ("", "null") else None

def svc_get(path, params):
    r = requests.get(f"{URL}/rest/v1/{path}", headers=svc_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def get_job(job_id):
    rows = svc_get("print_jobs", {"id": f"eq.{job_id}", "select": "id,status,attempts,printed_at,last_error,locked_by_device_id"})
    return rows[0] if rows else None

def attempts_count(job_id):
    rows = svc_get("print_job_attempts", {"print_job_id": f"eq.{job_id}", "select": "status"})
    return rows


def main():
    print(f"\n=== PRINT INTEGRATION TEST against {URL.replace('https://','')} ===\n")

    # configure the poller exactly like the real agent (service role)
    os.environ["CHEFSYNC_SUPABASE_URL"] = URL
    os.environ["CHEFSYNC_SUPABASE_KEY"] = SERVICE
    os.environ["CHEFSYNC_PRINT_SINK_DIR"] = os.path.join(os.path.dirname(__file__), "_virtual_jobs")

    uid, token = admin_create_user("owner")
    biz = user_rpc(token, "create_business_with_owner", {"p_name": "Print Diner", "p_location_name": "Main"})
    business_id, location_id = biz["business_id"], biz["location_id"]
    os.environ["CHEFSYNC_LOCATION_ID"] = location_id
    print(f"setup: user={uid[:8]} business={business_id[:8]} location={location_id[:8]}\n")

    payload = {"title": "ORDER 1", "items": [{"name": "Burger", "quantity": 2, "price": "25.00"}], "total": "25.00"}

    # ---- 1. DONE path (virtual printer) -------------------------------------
    j1 = user_rpc(token, "enqueue_print_job", {
        "p_location_id": location_id, "p_type": "receipt", "p_format": "text",
        "p_payload": payload, "p_options": {"printer_name": "virtual"}})
    status, jid = db_poller.process_one_job(support, log)
    check("enqueue + claim + print (virtual) -> done", status == "done" and jid == j1["id"], f"status={status}")
    job = get_job(j1["id"])
    check("job marked done + printed_at set", job and job["status"] == "done" and job["printed_at"], f"printed_at={job and job['printed_at']}")
    check("attempts == 1", job and job["attempts"] == 1, f"attempts={job and job['attempts']}")
    atts = [a["status"] for a in attempts_count(j1["id"])]
    check("print_job_attempts logged printing+done", "printing" in atts and "done" in atts, str(atts))

    # ---- 2. no double-claim -------------------------------------------------
    j2 = user_rpc(token, "enqueue_print_job", {
        "p_location_id": location_id, "p_type": "receipt", "p_format": "text",
        "p_payload": payload, "p_options": {"printer_name": "virtual"}})
    cfg = db_poller._config()
    first = db_poller.claim_job(cfg)
    second = db_poller.claim_job(cfg)
    check("second claim returns nothing (no double print)", first and first["id"] == j2["id"] and second is None,
          f"first={first and first['id'][:8]} second={second}")
    db_poller.mark_status(cfg, j2["id"], "done")  # release

    # ---- 3. FAILED path + retry/requeue + attempts --------------------------
    j3 = user_rpc(token, "enqueue_print_job", {
        "p_location_id": location_id, "p_type": "receipt", "p_format": "text",
        "p_payload": payload, "p_options": {"printer_name": "NoSuchPrinterXYZ"}})
    s1, _ = db_poller.process_one_job(support, log)   # attempt 1 -> requeue pending
    job = get_job(j3["id"])
    check("1st failure requeues to pending", s1 == "pending" and job["status"] == "pending", f"status={s1}")
    check("last_error recorded", bool(job and job["last_error"]), f"last_error={job and (job['last_error'] or '')[:40]}")
    db_poller.process_one_job(support, log)           # attempt 2 -> pending
    s3, _ = db_poller.process_one_job(support, log)   # attempt 3 -> failed (max)
    job = get_job(j3["id"])
    check("exhausts retries -> failed at max_attempts", job["status"] == "failed" and job["attempts"] == 3,
          f"status={job['status']} attempts={job['attempts']}")

    # ---- 4. empty queue -----------------------------------------------------
    s_empty, _ = db_poller.process_one_job(support, log)
    check("empty queue -> no job claimed", s_empty is None)

    # cleanup
    requests.patch(f"{URL}/rest/v1/businesses?id=eq.{business_id}", headers=svc_headers(),
                   json={"deleted_at": "now()"}, timeout=15)
    requests.delete(f"{URL}/auth/v1/admin/users/{uid}", headers=svc_headers(), timeout=15)
    print("\ncleanup: business soft-deleted + test user removed")

    print(f"\n=== {'ALL PRINT CHECKS PASSED ✅' if not fails else (str(len(fails)) + ' FAILED ❌: ' + ', '.join(fails))} ===\n")
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
