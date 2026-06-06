"""Configuration loader for chefsync-agent.

Resolves settings from (highest priority first):
  1. Environment variables (CHEFSYNC_*)
  2. A JSON config file, searched in:
       - $CHEFSYNC_CONFIG_FILE (explicit path)
       - chefsync-agent.config.json / config.json next to the .exe (or cwd in dev)
       - %APPDATA%\\ChefSync\\config.json   (Windows)
       - ~/.chefsync-agent/config.json      (any OS)

This lets a packaged Windows .exe be configured by dropping a JSON file next to
it (or in AppData) instead of setting environment variables.

Example chefsync-agent.config.json:
{
  "supabase_url": "https://<project>.supabase.co",
  "supabase_key": "<service_role key>",
  "location_id": "<location uuid>",
  "device_id": "",
  "poll_interval_ms": 3000
}
"""
import json
import os
import sys

CONFIG_FILENAMES = ["chefsync-agent.config.json", "config.json"]


def _base_dir():
    # When frozen (PyInstaller .exe), config lives next to the executable.
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.getcwd()


def config_search_paths():
    paths = []
    explicit = os.getenv("CHEFSYNC_CONFIG_FILE")
    if explicit:
        paths.append(explicit)
    for fn in CONFIG_FILENAMES:
        paths.append(os.path.join(_base_dir(), fn))
    appdata = os.getenv("APPDATA")
    if appdata:
        paths.append(os.path.join(appdata, "ChefSync", "config.json"))
    paths.append(os.path.join(os.path.expanduser("~"), ".chefsync-agent", "config.json"))
    return paths


def load_file_config():
    """Return the first readable JSON config as a dict (with __source__), else {}."""
    for path in config_search_paths():
        try:
            if path and os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    data["__source__"] = path
                    return data
        except Exception:
            continue
    return {}


def resolve(env_names, file_keys, file_cfg, default=""):
    """env vars win, then file keys, then default."""
    for name in env_names:
        value = os.getenv(name)
        if value:
            return value
    for key in file_keys:
        if file_cfg.get(key):
            return file_cfg.get(key)
    return default


def _write_path():
    """Preferred path for saving config (user-specific, not next to the exe)."""
    appdata = os.getenv("APPDATA")
    if appdata:
        return os.path.join(appdata, "ChefSync", "config.json")
    return os.path.join(os.path.expanduser("~"), ".chefsync-agent", "config.json")


def save_file_config(data: dict) -> str:
    """Persist config dict to the preferred user-specific path. Returns the path written."""
    path = _write_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {k: v for k, v in data.items() if not k.startswith("__")}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def clear_file_config() -> bool:
    """Delete the saved config file. Returns True if deleted, False if it didn't exist."""
    path = _write_path()
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False
