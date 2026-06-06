import os
import tempfile
from dataclasses import dataclass


# Origins allowed by default — includes the production dashboard and common dev
# ports. Override with CHEFSYNC_CORS_ORIGINS (comma-separated). Set to "*" to
# allow all (useful in fully-offline/LAN deployments, less secure).
_DEFAULT_ORIGINS = [
    "https://dashboard.chefsync.app",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3002",
]


def _split_origins(value):
    if not value:
        return _DEFAULT_ORIGINS
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class AppConfig:
    host: str
    port: int
    cors_origins: list
    health_interval_sec: int
    lock_name: str
    lock_file: str
    icon_path: str
    default_dpi: int
    default_width_px: int
    # HTTPS via mkcert — set CHEFSYNC_SSL_CERT + CHEFSYNC_SSL_KEY to enable.
    # See ssl/README.md for setup instructions.
    ssl_cert: str
    ssl_key: str


def load_config():
    return AppConfig(
        # localhost is treated differently from 127.0.0.1 by Chrome's Private
        # Network Access policy. Chrome may allow fetch() to "localhost" from
        # a public HTTPS origin without triggering PNA blocking.
        host=os.getenv("CHEFSYNC_HOST", "localhost"),
        port=int(os.getenv("CHEFSYNC_PORT", "5321")),
        cors_origins=_split_origins(os.getenv("CHEFSYNC_CORS_ORIGINS", "")),
        health_interval_sec=int(os.getenv("CHEFSYNC_HEALTH_INTERVAL_SEC", "10")),
        lock_name=os.getenv("CHEFSYNC_LOCK_NAME", "ChefsyncAgent"),
        lock_file=os.getenv(
            "CHEFSYNC_LOCK_FILE",
            os.path.join(tempfile.gettempdir(), "chefsync-agent.lock"),
        ),
        icon_path=os.getenv("CHEFSYNC_ICON_PATH", "icon.png"),
        default_dpi=int(os.getenv("CHEFSYNC_DEFAULT_DPI", "203")),
        default_width_px=int(os.getenv("CHEFSYNC_DEFAULT_WIDTH_PX", "576")),
        ssl_cert=os.getenv("CHEFSYNC_SSL_CERT", ""),
        ssl_key=os.getenv("CHEFSYNC_SSL_KEY", ""),
    )


@dataclass
class VirtualPrinterConfig:
    jobs_dir: str
    width_px: int
    left_margin_px: int
    right_margin_px: int


def load_virtual_printer_config():
    return VirtualPrinterConfig(
        jobs_dir=os.getenv(
            "CHEFSYNC_VP_JOBS_DIR",
            os.path.join(tempfile.gettempdir(), "chefsync-virtual-jobs"),
        ),
        width_px=int(os.getenv("CHEFSYNC_VP_WIDTH_PX", "576")),
        left_margin_px=int(os.getenv("CHEFSYNC_VP_LEFT_MARGIN_PX", "16")),
        right_margin_px=int(os.getenv("CHEFSYNC_VP_RIGHT_MARGIN_PX", "16")),
    )
