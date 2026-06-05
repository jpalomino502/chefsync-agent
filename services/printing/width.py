def get_printer_dpi(printer_name, support, default_dpi):
    if support.is_windows:
        try:
            dc = support.win32print.CreateDC("WINSPOOL", printer_name, None)
            dpi = support.win32print.GetDeviceCaps(dc, support.win32print.LOGPIXELSX)
            support.win32print.DeleteDC(dc)
            return dpi if dpi > 0 else default_dpi
        except Exception:
            return default_dpi
    return default_dpi


def get_target_width(printer_name, support, default_dpi, default_width_px, paper_mm=None):
    if paper_mm in ("58", "80"):
        dpi = get_printer_dpi(printer_name, support, default_dpi)
        mm = float(paper_mm)
        px = int(mm * dpi / 25.4)
        return px & ~7

    if support.is_windows:
        try:
            dc = support.win32print.CreateDC("WINSPOOL", printer_name, None)
            width_px = support.win32print.GetDeviceCaps(dc, support.win32print.PHYSICALWIDTH)
            support.win32print.DeleteDC(dc)
            return width_px & ~7 if width_px > 0 else default_width_px
        except Exception:
            pass
    return default_width_px
