"""Cross-platform printer discovery in the chefsync-agent contract shape.

Returns dicts of:
  { id, name, connection_type, is_default, status, capabilities }

Backends: Windows win32print, CUPS (pycups) where available, otherwise the
`lpstat`/`lp` CLI (covers macOS and Linux without pycups).
"""
import shutil
import subprocess


def _cli_available():
    return shutil.which("lpstat") is not None and shutil.which("lp") is not None


def _lpstat_printers():
    names, default = [], None
    try:
        out = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, timeout=5)
        for line in out.stdout.splitlines():
            parts = line.split()
            # English "printer NAME is idle" / Spanish "impresora NAME ..."
            if len(parts) >= 2 and parts[0] in ("printer", "impresora"):
                names.append(parts[1])
    except Exception:
        pass
    try:
        d = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=5)
        line = (d.stdout or "").strip()
        # "system default destination: NAME"
        if ":" in line:
            default = line.split(":", 1)[1].strip() or None
    except Exception:
        pass
    return names, default


def _virtual_device():
    return {
        "id": "virtual",
        "name": "Virtual (file sink)",
        "connection_type": "system",
        "is_default": False,
        "status": "available",
        "capabilities": {"paper_width": 80, "raw": True, "html": False, "text": True, "escpos": True, "virtual": True},
    }


def discover_devices(support):
    """Return the list of printers in the contract shape (never raises).

    Always includes a 'virtual' device that writes jobs to a file — handy for
    setup/testing before a physical printer is configured.
    """
    devices = [_virtual_device()]

    # Windows
    if getattr(support, "is_windows", False) and support.win32print is not None:
        try:
            flags = support.win32print.PRINTER_ENUM_LOCAL | support.win32print.PRINTER_ENUM_CONNECTIONS
            try:
                default_name = support.win32print.GetDefaultPrinter()
            except Exception:
                default_name = None
            for printer in support.win32print.EnumPrinters(flags):
                name = printer[2]
                devices.append(_device(name, "system", name == default_name))
            return devices
        except Exception:
            return devices

    # CUPS via pycups
    if getattr(support, "cups", None) is not None:
        try:
            conn = support.cups.Connection()
            default_name = None
            try:
                default_name = conn.getDefault()
            except Exception:
                pass
            for name in conn.getPrinters().keys():
                devices.append(_device(name, "system", name == default_name))
            return devices
        except Exception:
            pass  # fall through to CLI

    # macOS / Linux via lpstat
    if _cli_available():
        names, default = _lpstat_printers()
        for name in names:
            devices.append(_device(name, "system", name == default))
    return devices


def _device(name, connection_type, is_default):
    return {
        "id": name,            # printer name is the stable id the app stores
        "name": name,
        "connection_type": connection_type,
        "is_default": bool(is_default),
        "status": "available",
        "capabilities": {"paper_width": 80, "raw": True, "html": False, "text": True, "escpos": True},
    }
