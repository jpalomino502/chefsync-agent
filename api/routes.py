from datetime import datetime, timezone

from flask import jsonify, request, current_app

from services.printing.discovery import list_printers
from services.printing.driver import print_text, print_image
from services.printing.devices import discover_devices
from services.printing.dispatch import print_job
from services.device import get_device_id

AGENT_NAME = "chefsync-agent"
AGENT_VERSION = "1.0.0"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def register_routes(app):
    # =========================================================================
    # chefsync-agent v1 contract endpoints
    # =========================================================================
    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({
            "ok": True,
            "agent": AGENT_NAME,
            "version": AGENT_VERSION,
            "device_id": get_device_id(),
        })

    @app.route("/printers", methods=["GET"])
    def printers():
        support = current_app.config["SUPPORT"]
        try:
            return jsonify({"ok": True, "printers": discover_devices(support)})
        except Exception as exc:  # never 500 the discovery endpoint
            current_app.logger.warning("printers discovery failed: %s", exc)
            return jsonify({"ok": True, "printers": [], "warning": str(exc)})

    @app.route("/print", methods=["POST"])
    def do_print():
        support = current_app.config["SUPPORT"]
        data = request.get_json(silent=True) or {}
        job_id = data.get("job_id")
        printer = data.get("printer_id") or data.get("printer_name")
        job_type = data.get("type", "receipt")
        fmt = data.get("format", "text")
        payload = data.get("payload") or {}
        options = data.get("options") or {}

        if not printer:
            return jsonify({"ok": False, "job_id": job_id, "error": "printer_id is required"}), 400
        try:
            print_job(support, printer, job_type, fmt, payload, options)
            current_app.logger.info("printed job %s on %s (%s/%s)", job_id, printer, job_type, fmt)
            return jsonify({"ok": True, "job_id": job_id, "printed_at": _now_iso()})
        except Exception as exc:
            current_app.logger.error("print failed for job %s: %s", job_id, exc)
            return jsonify({"ok": False, "job_id": job_id, "error": str(exc)}), 500

    @app.route("/print/test", methods=["POST"])
    def do_print_test():
        support = current_app.config["SUPPORT"]
        data = request.get_json(silent=True) or {}
        printer = data.get("printer_id") or data.get("printer_name")
        if not printer:
            devices = discover_devices(support)
            default = next((d for d in devices if d["is_default"]), None) or (devices[0] if devices else None)
            printer = default["id"] if default else None
        if not printer:
            return jsonify({"ok": False, "error": "no printer available"}), 400

        payload = {
            "title": "CHEFSYNC TEST",
            "lines": [
                "CHEFSYNC TEST PRINT".center(32),
                "-" * 32,
                "Device: " + get_device_id()[:8],
                "Printer: " + str(printer),
                "Time: " + _now_iso(),
                "-" * 32,
                "If you can read this, printing",
                "is working correctly.",
            ],
        }
        try:
            print_job(support, printer, "test", "text", payload, {})
            return jsonify({"ok": True, "job_id": data.get("job_id"), "printed_at": _now_iso()})
        except Exception as exc:
            current_app.logger.error("test print failed: %s", exc)
            return jsonify({"ok": False, "job_id": data.get("job_id"), "error": str(exc)}), 500

    # =========================================================================
    # legacy endpoints (kept for backward compatibility)
    # =========================================================================
    @app.route("/impresoras", methods=["GET"])
    def get_printers():
        support = current_app.config["SUPPORT"]
        try:
            support.require_printing_support()
            return jsonify(list_printers(support))
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.route("/imprimir", methods=["POST"])
    def print_route():
        support = current_app.config["SUPPORT"]
        config = current_app.config["APP_CONFIG"]
        try:
            support.require_printing_support()
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

        if "file" in request.files:
            printer = request.form.get("printer_name")
            if not printer:
                return jsonify({"error": "printer_name required"}), 400
            file = request.files["file"]
            paper_mm = request.form.get("paper_mm")
            dither = request.form.get("dither", "floyd")
            threshold = int(request.form.get("threshold", 128))
            contrast = float(request.form.get("contrast", 1.0))
            return jsonify(
                print_image(
                    printer,
                    file,
                    support,
                    config,
                    paper_mm=paper_mm,
                    dither=dither,
                    threshold=threshold,
                    contrast=contrast,
                )
            )

        data = request.get_json(silent=True) or {}
        if "printer_name" not in data or "invoice_design" not in data:
            return jsonify({"error": "Datos incompletos"}), 400
        return jsonify(print_text(data["printer_name"], data["invoice_design"], support))
