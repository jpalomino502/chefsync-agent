import hashlib
import logging
import os
import threading
import time
import tkinter as tk

from PIL import Image, ImageTk, ImageFont

from config import load_virtual_printer_config
from virtual_printer.server import serve, serve_raw, job_bases, read_prn_text
from virtual_printer.render import render_preview_png, derive_width_px_from_data, text_line_width

logger = logging.getLogger("chefsync.viewer")


class ViewerApp:
    def __init__(self, config=None):
        self.config = config or load_virtual_printer_config()
        self.root = tk.Tk()
        self.root.title("Impresora Térmica Virtual")
        self.width_px = self.config.width_px
        self.lpd_server_ref = {}
        self.raw_server_ref = {}
        self.mm_var = tk.StringVar(value="80")
        self.dpi_var = tk.StringVar(value="203")
        self.listbox = tk.Listbox(self.root, width=40)
        self.listbox.grid(row=0, column=0, sticky="ns")
        self.canvas = tk.Canvas(self.root, width=self.width_px, height=480, bg="#ffffff")
        self.canvas.grid(row=0, column=1, sticky="nsew")
        self.vscroll = tk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.vscroll.grid(row=0, column=2, sticky="ns")
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.status = tk.Label(self.root, text="", anchor="w")
        self.status.grid(row=1, column=0, columnspan=3, sticky="ew")
        self.mm_menu = tk.OptionMenu(self.root, self.mm_var, "58", "80", command=self._on_paper_change)
        self.mm_menu.grid(row=2, column=1, sticky="ew")
        self.dpi_menu = tk.OptionMenu(self.root, self.dpi_var, "203", "300", command=self._on_paper_change)
        self.dpi_menu.grid(row=2, column=2, sticky="ew")
        self.auto_var = tk.IntVar(value=0)
        self.auto_chk = tk.Checkbutton(self.root, text="Auto ancho", variable=self.auto_var, command=self._on_paper_change)
        self.auto_chk.grid(row=2, column=0, sticky="ew")
        self.clear_btn = tk.Button(self.root, text="Borrar todo", command=self._clear_all)
        self.clear_btn.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.root.columnconfigure(1, weight=1)
        self.root.columnconfigure(2, weight=0)
        self.root.rowconfigure(0, weight=1)
        try:
            self.font = ImageFont.truetype("consola.ttf", 18)
        except Exception:
            self.font = ImageFont.load_default()
        self.photo = None
        self.jobs = []
        self.hash_times = {}
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)
        self._start_server()
        self._schedule_refresh()

    def _start_server(self):
        logger.info("[viewer] starting LPD server on port 5515")
        threading.Thread(target=serve, args=("0.0.0.0", 5515, self.config.jobs_dir, self.lpd_server_ref), daemon=True).start()
        logger.info("[viewer] starting RAW server on port 9100")
        threading.Thread(target=serve_raw, args=("0.0.0.0", 9100, self.config.jobs_dir, self.raw_server_ref), daemon=True).start()

    def _schedule_refresh(self):
        self._refresh_jobs()
        self.root.after(1000, self._schedule_refresh)

    def _refresh_jobs(self):
        try:
            bases = job_bases(self.config.jobs_dir)
        except Exception as exc:
            logger.error("[viewer] scanning dir %s: %s", self.config.jobs_dir, exc)
            return
        if bases != self.jobs:
            logger.info("[viewer] detected %d job(s) in %s (was %d)", len(bases), self.config.jobs_dir, len(self.jobs))
            self.jobs = bases
            self.listbox.delete(0, tk.END)
            for base in self.jobs:
                self.listbox.insert(tk.END, os.path.basename(base))
            if self.jobs:
                self.listbox.select_set(0)
                self._display_job(self.jobs[0])
        if self.jobs:
            self._analyze_latest(self.jobs[0])

    def _on_select(self, _evt):
        sel = self.listbox.curselection()
        if not sel:
            return
        base = self.jobs[sel[0]]
        self._display_job(base)

    def _display_job(self, base):
        png = base + ".png"
        data, _ = read_prn_text(base)
        logger.info("[viewer] rendering %s (%d bytes) -> %s", os.path.basename(base), len(data), os.path.basename(png))
        width = self.width_px
        if self.auto_var.get() == 1:
            width = derive_width_px_from_data(data, width)
            self.width_px = width
            self.canvas.config(width=width)
        try:
            cuts = render_preview_png(
                data,
                png,
                width,
                self.config.left_margin_px,
                self.config.right_margin_px,
            )
        except Exception as exc:
            logger.error("[viewer] render error for %s: %s", os.path.basename(base), exc)
            cuts = []
        try:
            img = Image.open(png)
        except Exception:
            img = Image.new("L", (width, 120), 255)
        ratio = width / float(img.width)
        height = int(img.height * ratio)
        disp = img.resize((width, height))
        self.photo = ImageTk.PhotoImage(disp.convert("RGB"))
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.create_line(
            self.config.left_margin_px,
            0,
            self.config.left_margin_px,
            height,
            fill="#cccccc",
            width=1,
            dash=(4, 2),
        )
        self.canvas.create_line(
            width - self.config.right_margin_px,
            0,
            width - self.config.right_margin_px,
            height,
            fill="#cccccc",
            width=1,
            dash=(4, 2),
        )
        for cut_y in cuts:
            scaled_y = int(cut_y * ratio)
            self.canvas.create_line(
                self.config.left_margin_px,
                scaled_y,
                width - self.config.right_margin_px,
                scaled_y,
                fill="#ff0000",
                width=2,
                dash=(6, 4),
            )

    def _analyze_latest(self, base):
        data, txt = read_prn_text(base)
        h = hashlib.sha256(data).hexdigest()
        now = time.time()
        recent = self.hash_times.get(h, [])
        recent.append(now)
        self.hash_times[h] = [t for t in recent if now - t <= 10]
        loop = len(self.hash_times[h]) >= 3
        lines = txt.splitlines() if txt else []
        long_lines = 0
        for line in lines:
            width = text_line_width(line, self.font)
            effective_width = max(
                16,
                self.width_px - self.config.left_margin_px - self.config.right_margin_px - 16,
            )
            if width >= effective_width:
                long_lines += 1
        cut_risk = long_lines > 0
        info = []
        info.append(f"Trabajos iguales en 10s: {len(self.hash_times[h])}")
        if loop:
            info.append("Posible bucle de impresión")
        info.append(f"Líneas: {len(lines)}")
        if cut_risk:
            info.append("Riesgo de corte por ancho")
        info.append(f"Tamaño: {len(data)} bytes")
        self.status.config(text=" | ".join(info))

    def _clear_all(self):
        try:
            for name in os.listdir(self.config.jobs_dir):
                path = os.path.join(self.config.jobs_dir, name)
                try:
                    os.remove(path)
                except Exception:
                    pass
            self.jobs = []
            self.listbox.delete(0, tk.END)
            self.canvas.delete("all")
            self.status.config(text="")
            self.hash_times = {}
        except Exception:
            pass

    def _on_mousewheel(self, evt):
        delta = 0
        try:
            delta = int(-evt.delta / 120)
        except Exception:
            pass
        if delta == 0:
            delta = -1 if getattr(evt, "num", 0) == 4 else 1
        self.canvas.yview_scroll(delta, "units")

    def _on_paper_change(self, _val=None):
        try:
            mm = float(self.mm_var.get())
            dpi = float(self.dpi_var.get())
            self.width_px = int(mm * dpi / 25.4)
        except Exception:
            return
        self.canvas.config(width=self.width_px)
        sel = self.listbox.curselection()
        if sel:
            base = self.jobs[sel[0]]
            self._display_job(base)

    def run(self):
        self.root.mainloop()


def main():
    app = ViewerApp()
    app.run()


if __name__ == "__main__":
    main()
