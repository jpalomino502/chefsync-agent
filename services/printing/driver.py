import os
import tempfile

from PIL import Image

from services.printing.escpos import img_to_escpos
from services.printing.width import get_target_width


def print_text(printer_name, text, support):
    payload = text + "\n\n\n\x1B\x64\x05\x1B\x69"
    encoded = payload.encode("utf-8")

    if support.is_windows:
        try:
            handle = support.win32print.OpenPrinter(printer_name)
            support.win32print.StartDocPrinter(handle, 1, ("Text", None, "RAW"))
            support.win32print.StartPagePrinter(handle)
            support.win32print.WritePrinter(handle, encoded)
            support.win32print.EndPagePrinter(handle)
            support.win32print.EndDocPrinter(handle)
            support.win32print.ClosePrinter(handle)
            return {"status": "success"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    if support.is_linux:
        try:
            conn = support.cups.Connection()
            with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".prn") as handle:
                handle.write(encoded)
                temp = handle.name
            conn.printFile(printer_name, temp, "Text", {"raw": "true"})
            os.unlink(temp)
            return {"status": "success"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    return {"status": "error", "error": "OS no soportado"}


def print_image(printer_name, file_storage, support, config, paper_mm=None, dither="floyd", threshold=128, contrast=1.0):
    try:
        img = Image.open(file_storage.stream)
        target_width = get_target_width(
            printer_name,
            support,
            config.default_dpi,
            config.default_width_px,
            paper_mm=paper_mm,
        )
        esc_data = img_to_escpos(img, target_width, dither, threshold, contrast)
        if support.is_windows:
            handle = support.win32print.OpenPrinter(printer_name)
            support.win32print.StartDocPrinter(handle, 1, ("Image", None, "RAW"))
            support.win32print.StartPagePrinter(handle)
            support.win32print.WritePrinter(handle, esc_data)
            support.win32print.EndPagePrinter(handle)
            support.win32print.EndDocPrinter(handle)
            support.win32print.ClosePrinter(handle)
            return {"status": "success"}
        if support.is_linux:
            conn = support.cups.Connection()
            with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".prn") as handle:
                handle.write(esc_data)
                temp = handle.name
            conn.printFile(printer_name, temp, "Image", {"raw": "true"})
            os.unlink(temp)
            return {"status": "success"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    return {"status": "error", "error": "OS no soportado"}
