"""Stable per-install device identity for chefsync-agent."""
import os
import uuid


def _device_file():
    return os.getenv(
        "CHEFSYNC_DEVICE_FILE",
        os.path.join(os.path.expanduser("~"), ".chefsync-agent", "device_id"),
    )


def get_device_id():
    """Return a stable UUID for this agent install, persisted to disk."""
    path = _device_file()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                value = handle.read().strip()
                if value:
                    return value
        os.makedirs(os.path.dirname(path), exist_ok=True)
        value = str(uuid.uuid4())
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(value)
        return value
    except Exception:
        # last-resort deterministic id so /health never crashes
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, "chefsync-agent"))
