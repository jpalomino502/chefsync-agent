"""Send a print job to a printer, cross-platform.

Accepts the chefsync-agent /print contract (type/format/payload) and renders it
to bytes, then writes to the printer via win32print (RAW), CUPS, or the `lp` CLI.
"""
import base64
import logging
import os
import re
import shutil
import subprocess
import tempfile

logger = logging.getLogger("chefsync.dispatch")

# Resolve `lp` to an absolute path ONCE. A daemonized agent often has a minimal
# PATH (no /usr/bin), which made subprocess.run(["lp", ...]) fail with
# FileNotFoundError -> "lp: No such file or directory" even though lp exists.
_LP_BIN = shutil.which("lp") or next((p for p in ("/usr/bin/lp", "/bin/lp") if os.path.exists(p)), None)

# ESC/POS cut + feed, appended to plain text jobs
_FEED_CUT = b"\n\n\n\x1b\x64\x05\x1b\x69"


def _strip_html(html):
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_text(job_type, payload):
    """Build a simple monospace receipt from the payload (best-effort)."""
    payload = payload or {}
    if isinstance(payload.get("text"), str):
        return payload["text"]
    if isinstance(payload.get("lines"), list):
        return "\n".join(str(line) for line in payload["lines"])
    if isinstance(payload.get("html"), str):
        return _strip_html(payload["html"])

    lines = []
    title = payload.get("title") or payload.get("business_name") or f"CHEFSYNC — {str(job_type).upper()}"
    lines.append(str(title).center(32))
    if payload.get("order_number") is not None:
        lines.append(f"Order #{payload['order_number']}")
    if payload.get("table"):
        lines.append(f"Table: {payload['table']}")
    if payload.get("customer"):
        lines.append(f"Customer: {payload['customer']}")
    lines.append("-" * 32)
    for item in payload.get("items", []) or []:
        name = str(item.get("name", "item"))
        qty = item.get("quantity", item.get("qty", 1))
        price = item.get("price", item.get("total"))
        left = f"{qty} x {name}"[:24]
        right = "" if price is None else f"{price}"
        lines.append(f"{left:<24}{right:>8}")
        for opt in item.get("options", []) or []:
            lines.append(f"  + {opt.get('name', '')}")
    if payload.get("total") is not None:
        lines.append("-" * 32)
        lines.append(f"{'TOTAL':<24}{payload['total']:>8}")
    return "\n".join(lines)


def _decode_escpos(payload):
    payload = payload or {}
    raw = payload.get("data") or payload.get("escpos") or ""
    if payload.get("encoding") == "base64" or _looks_base64(raw):
        try:
            return base64.b64decode(raw)
        except Exception:
            pass
    return str(raw).encode("utf-8", "replace")


def _looks_base64(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9+/=\s]+", value or "")) and len(value) % 4 == 0 and len(value) > 16


# Reserved printer id that writes the rendered job to a file instead of paper.
# Useful for headless dev / CI and for an "is the pipeline working" check.
VIRTUAL_PRINTER_ID = "virtual"


def _virtual_sink_dir():
    return os.getenv("CHEFSYNC_PRINT_SINK_DIR", os.path.join(tempfile.gettempdir(), "chefsync-virtual-jobs"))


def _is_virtual(printer_name):
    return str(printer_name).lower() == VIRTUAL_PRINTER_ID


def _send_raw(support, printer_name, data, title="ChefSync"):
    n = len(data)
    # Virtual file sink (no hardware) — writes the bytes to a file and succeeds.
    if _is_virtual(printer_name):
        out_dir = _virtual_sink_dir()
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{title.replace(' ', '_')}-{os.getpid()}-{len(os.listdir(out_dir))}.prn")
        logger.info("[dispatch] backend=virtual_sink dir=%s bytes=%d", out_dir, n)
        with open(path, "wb") as handle:
            handle.write(data)
        logger.info("[virtual_sink] wrote file=%s bytes=%d", path, n)
        return

    # Windows RAW
    if getattr(support, "is_windows", False) and support.win32print is not None:
        logger.info("[dispatch] backend=win32 printer=%r bytes=%d", printer_name, n)
        handle = support.win32print.OpenPrinter(printer_name)
        try:
            support.win32print.StartDocPrinter(handle, 1, (title, None, "RAW"))
            support.win32print.StartPagePrinter(handle)
            support.win32print.WritePrinter(handle, data)
            support.win32print.EndPagePrinter(handle)
            support.win32print.EndDocPrinter(handle)
        finally:
            support.win32print.ClosePrinter(handle)
        logger.info("[win32] sent to spooler printer=%r bytes=%d", printer_name, n)
        return

    # CUPS (pycups)
    if getattr(support, "cups", None) is not None:
        logger.info("[dispatch] backend=cups printer=%r bytes=%d", printer_name, n)
        conn = support.cups.Connection()
        tmp = tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".prn")
        try:
            tmp.write(data)
            tmp.close()
            job_id = conn.printFile(printer_name, tmp.name, title, {"raw": "true"})
            logger.info("[cups] printFile printer=%r cups_job_id=%s", printer_name, job_id)
        finally:
            os.unlink(tmp.name)
        return

    # macOS / Linux CLI
    if not printer_name:
        raise RuntimeError("printer_name required for lp")
    if not _LP_BIN:
        raise RuntimeError("lp binary not found on PATH (install CUPS / check PATH)")
    args = [_LP_BIN, "-d", printer_name, "-o", "raw", "-t", title]
    logger.info("[dispatch] backend=lp command=%s bytes=%d", " ".join(args), n)
    try:
        proc = subprocess.run(args, input=data, capture_output=True, timeout=30)
    except FileNotFoundError as exc:
        raise RuntimeError("lp not executable: %s" % exc)
    out = proc.stdout.decode("utf-8", "ignore").strip()
    err = proc.stderr.decode("utf-8", "ignore").strip()
    logger.info("[lp] exit=%d stdout=%r stderr=%r", proc.returncode, out, err)
    if proc.returncode != 0:
        # lp prints e.g. "lp: The printer or class does not exist." to stderr
        raise RuntimeError(err or out or ("lp failed (exit %d)" % proc.returncode))


def print_job(support, printer_name, job_type, fmt, payload, options=None):
    """Render + send a job. Returns None on success, raises on failure."""
    fmt = (fmt or "text").lower()
    if not printer_name:
        raise ValueError("printer_id/printer_name is required")

    if fmt == "escpos":
        data = _decode_escpos(payload)
    else:
        text = build_text(job_type, payload)
        data = text.encode("utf-8", "replace") + _FEED_CUT

    copies = int((options or {}).get("copies", 1) or 1)
    logger.info("[dispatch] print_job printer=%r type=%s fmt=%s copies=%d bytes=%d",
                printer_name, job_type, fmt, copies, len(data))
    for _ in range(max(1, copies)):
        _send_raw(support, printer_name, data, title=f"ChefSync {job_type}")
