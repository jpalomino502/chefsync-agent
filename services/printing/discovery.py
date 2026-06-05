def list_printers(support):
    if support.is_windows:
        flags = support.win32print.PRINTER_ENUM_LOCAL | support.win32print.PRINTER_ENUM_CONNECTIONS
        printers = support.win32print.EnumPrinters(flags)
        result = []
        for printer in printers:
            name = printer[2]
            try:
                handle = support.win32print.OpenPrinter(name)
                devmode = support.win32print.GetPrinter(handle, 2)["pDevMode"]
                width_mm = devmode.dmPaperWidth if getattr(devmode, "dmPaperWidth", 0) > 0 else 80
                support.win32print.ClosePrinter(handle)
            except Exception:
                width_mm = 80
            result.append({"name": name, "paper_size": f"{width_mm}mm", "width_mm": width_mm})
        return result

    if support.is_linux:
        try:
            conn = support.cups.Connection()
            return [{"name": k, "paper_size": "80mm", "width_mm": 80} for k in conn.getPrinters()]
        except Exception:
            return []

    return []
