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
from pathlib import Path

from config import get_virtual_sink_dir_from_env

logger = logging.getLogger("chefsync.dispatch")

_LP_BIN = shutil.which("lp") or next((p for p in ("/usr/bin/lp", "/bin/lp") if os.path.exists(p)), None)

_FEED_CUT = b"\n\n\n\x1b\x64\x05\x1b\x69"


def _available_lp_printers():
    """Return set of CUPS printer names via lpstat, or None if lpstat unavailable."""
    lpstat = shutil.which("lpstat")
    if not lpstat:
        return None
    try:
        proc = subprocess.run([lpstat, "-p"], capture_output=True, text=True, timeout=5)
        names = set()
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in ("printer", "impresora"):
                names.add(parts[1])
        return names
    except Exception:
        return None


def _strip_html(html):
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_text(job_type, payload):
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


VIRTUAL_PRINTER_ID = "virtual"
_VIRTUAL_ALIASES = {
    "virtual",
    "virtual printer",
    "virtual (file sink)",
    "chefsync virtual",
    "chefsync virtual printer",
}


def _virtual_sink_dir():
    return get_virtual_sink_dir_from_env()


def _is_virtual(printer_name):
    if not printer_name:
        return False
    return str(printer_name).strip().lower() in _VIRTUAL_ALIASES


def _send_raw(support, printer_name, data, title="ChefSync"):
    n = len(data)
    if _is_virtual(printer_name):
        out_dir = _virtual_sink_dir()

        try:
            Path(out_dir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("[dispatch] cannot create virtual sink dir %s: %s", out_dir, exc)
            raise RuntimeError(f"Cannot create virtual sink directory {out_dir}: {exc}") from exc

        existing = list(Path(out_dir).glob("*.prn"))
        safe_title = str(title or "ChefSync").replace(" ", "_")
        path = Path(out_dir) / f"{safe_title}-{os.getpid()}-{len(existing)}.prn"

        logger.info("[dispatch] backend=virtual_sink dir=%s file=%s bytes=%d", out_dir, path, n)

        with open(path, "wb") as handle:
            handle.write(data)

        if not path.exists() or path.stat().st_size <= 0:
            raise RuntimeError(f"Virtual print file was not created correctly: {path}")

        logger.info("[virtual_sink] wrote file=%s bytes=%d (verified)", path, path.stat().st_size)
        return

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

    lp_bin = shutil.which("lp") or next((p for p in ("/usr/bin/lp", "/bin/lp") if os.path.exists(p)), None)
    if not printer_name:
        raise RuntimeError("printer_name is required for lp backend (no printer specified)")
    if not lp_bin:
        raise RuntimeError("lp binary not found — install CUPS or add /usr/bin to PATH")
    printers = _available_lp_printers()
    if printers is not None and printer_name not in printers:
        avail = ", ".join(sorted(printers)) if printers else "(none)"
        raise RuntimeError(
            f"Printer {printer_name!r} not found in OS print queues. "
            f"Available: [{avail}]. Install or share the printer first."
        )
    args = [lp_bin, "-d", printer_name, "-o", "raw", "-t", title]
    logger.info("[dispatch] backend=lp command=%s bytes=%d", " ".join(args), n)
    try:
        proc = subprocess.run(args, input=data, capture_output=True, timeout=30)
    except FileNotFoundError as exc:
        raise RuntimeError(f"lp binary not executable: {exc}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"lp timed out after 30s sending to {printer_name!r}")
    out = proc.stdout.decode("utf-8", "ignore").strip()
    err = proc.stderr.decode("utf-8", "ignore").strip()
    logger.info("[lp] exit=%d stdout=%r stderr=%r", proc.returncode, out, err)
    if proc.returncode != 0:
        combined = err or out or f"lp failed (exit {proc.returncode})"
        if "No such file" in combined or "does not exist" in combined or "unknown destination" in combined:
            printers = _available_lp_printers() or set()
            avail = ", ".join(sorted(printers)) if printers else "(none)"
            raise RuntimeError(
                f"Printer {printer_name!r} not found in OS print queues (lp error: {combined}). "
                f"Available: [{avail}]"
            )
        raise RuntimeError(combined)


def print_job(support, printer_name, job_type, fmt, payload, options=None):
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
    for i in range(max(1, copies)):
        logger.info("[dispatch] sending copy %d/%d to %r", i + 1, max(1, copies), printer_name)
        _send_raw(support, printer_name, data, title=f"ChefSync {job_type}")
    logger.info("[dispatch] print_job complete printer=%r copies=%d", printer_name, copies)