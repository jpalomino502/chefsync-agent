import os
import platform


class PlatformSupport:
    def __init__(self):
        self.system = platform.system()
        system_lower = self.system.lower()
        self.is_windows = system_lower.startswith("win")
        self.is_linux = system_lower.startswith("linux")
        self.is_macos = system_lower.startswith("darwin") or system_lower.startswith("mac")
        self.is_posix = self.is_linux or self.is_macos

        self.win32print = None
        self.win32event = None
        self.win32api = None
        self.winerror = None
        self.fcntl = None
        self.cups = None
        self.pystray = None

        self._load_optional_modules()

    def _load_optional_modules(self):
        if self.is_windows:
            try:
                import win32print
                import win32event
                import win32api
                import winerror

                self.win32print = win32print
                self.win32event = win32event
                self.win32api = win32api
                self.winerror = winerror
            except Exception:
                pass

        if self.is_posix:
            try:
                import fcntl

                self.fcntl = fcntl
            except Exception:
                pass

            try:
                import cups

                self.cups = cups
            except Exception:
                pass

        try:
            import pystray

            self.pystray = {
                "Menu": pystray.Menu,
                "MenuItem": pystray.MenuItem,
                "Icon": pystray.Icon,
            }
        except Exception:
            self.pystray = None

    @property
    def printing_supported(self):
        if self.is_windows:
            return self.win32print is not None
        if self.is_posix:
            return self.cups is not None
        return False

    def require_printing_support(self):
        if self.printing_supported:
            return
        if os.getenv("CHEFSYNC_REQUIRE_PRINTING", "0") == "1":
            raise RuntimeError("Printing support not available on this platform")
