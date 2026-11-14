"""HomeNet Monitor launcher.

Double-click (or use the desktop shortcut) to control HomeNet and AdGuard Home, open their pages, and choose
whether HomeNet starts with Windows. Closing this window leaves everything running in the background.

    pythonw HomeNet.pyw                 normal window
    pythonw HomeNet.pyw --autostart     start HomeNet straight away (used by the Windows startup shortcut)
    pythonw HomeNet.pyw --minimized     start minimised
"""
import pathlib
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from launcher import core  # noqa: E402

BRAND, BRAND_DARK = "#2549ea", "#1d38d7"
BG, CARD, BORDER = "#f1f5f9", "#ffffff", "#e2e8f0"
TEXT, MUTED = "#0f172a", "#64748b"
GREEN, RED, AMBER, GREY = "#10b981", "#ef4444", "#f59e0b", "#94a3b8"
FONT = "Segoe UI"


class Card(tk.Frame):
    """White rounded-look panel with a title row and a status pill."""

    def __init__(self, parent, title: str, subtitle: str):
        super().__init__(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        top = tk.Frame(self, bg=CARD)
        top.pack(fill="x", padx=16, pady=(14, 2))
        left = tk.Frame(top, bg=CARD)
        left.pack(side="left", fill="x", expand=True)
        tk.Label(left, text=title, bg=CARD, fg=TEXT, font=(FONT, 12, "bold")).pack(anchor="w")
        tk.Label(left, text=subtitle, bg=CARD, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        self.pill = tk.Frame(top, bg=BG)
        self.pill.pack(side="right")
        self.dot = tk.Canvas(self.pill, width=10, height=10, bg=BG, highlightthickness=0)
        self.dot_id = self.dot.create_oval(1, 1, 9, 9, fill=GREY, outline="")
        self.dot.pack(side="left", padx=(8, 4), pady=5)
        self.state = tk.Label(self.pill, text="Checking…", bg=BG, fg=TEXT, font=(FONT, 9, "bold"))
        self.state.pack(side="left", padx=(0, 10))
        self.link = tk.Label(self, text="", bg=CARD, fg=BRAND, font=(FONT, 9, "underline"), cursor="hand2")
        self.link.pack(anchor="w", padx=16)
        self.body = tk.Frame(self, bg=CARD)
        self.body.pack(fill="x", padx=16, pady=(8, 14))

    def set_state(self, colour: str, text: str, link: str = ""):
        self.dot.itemconfigure(self.dot_id, fill=colour)
        self.state.configure(text=text)
        self.link.configure(text=link)


class Launcher(tk.Tk):
    def __init__(self, autostart: bool, minimized: bool):
        super().__init__()
        self.title("HomeNet Monitor")
        self.geometry("500x750")
        self.minsize(480, 720)
        self.configure(bg=BG)
        self.busy = {"homenet": False, "adguard": False}
        self.hn_running = None
        self.ag_state = None
        self._style()
        self._build()
        if minimized:
            self.iconify()
        self.after(150, self._poll)
        self.after(300, self._tick)
        if autostart:
            self.after(400, lambda: self._homenet(core.start, open_after=False))

    # ------------------------------------------------------------ look
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(".", font=(FONT, 10))
        s.configure("Primary.TButton", font=(FONT, 10, "bold"), foreground="white", background=BRAND, borderwidth=0,
                    focusthickness=0, padding=(14, 8))
        s.map("Primary.TButton", background=[("disabled", "#a5b8f8"), ("active", BRAND_DARK)],
              foreground=[("disabled", "#eef2ff")])
        s.configure("TButton", background="#eef2f7", foreground=TEXT, borderwidth=0, focusthickness=0, padding=(12, 7))
        s.map("TButton", background=[("active", BORDER), ("disabled", "#f8fafc")], foreground=[("disabled", "#b6c0cc")])
        s.configure("Danger.TButton", background="#fee2e2", foreground="#b91c1c", borderwidth=0, padding=(12, 7))
        s.map("Danger.TButton", background=[("active", "#fecaca"), ("disabled", "#f8fafc")], foreground=[("disabled", "#b6c0cc")])
        s.configure("Green.TButton", font=(FONT, 10, "bold"), foreground="white", background="#059669", borderwidth=0,
                    focusthickness=0, padding=(14, 8))
        s.map("Green.TButton", background=[("disabled", "#a7e3cf"), ("active", "#047857")],
              foreground=[("disabled", "#ecfdf5")])
        s.configure("Card.TCheckbutton", background=CARD, foreground=TEXT)
        s.map("Card.TCheckbutton", background=[("active", CARD)])

    def _build(self):
        # Header band
        head = tk.Frame(self, bg=BRAND)
        head.pack(fill="x")
        inner = tk.Frame(head, bg=BRAND)
        inner.pack(fill="x", padx=20, pady=16)
        logo = tk.Canvas(inner, width=40, height=40, bg=BRAND, highlightthickness=0)
        logo.create_oval(2, 2, 38, 38, fill="white", outline="")
        logo.create_arc(10, 12, 30, 32, start=30, extent=120, style="arc", outline=BRAND, width=3)
        logo.create_arc(14, 17, 26, 29, start=30, extent=120, style="arc", outline=BRAND, width=3)
        logo.create_oval(18, 25, 22, 29, fill=BRAND, outline="")
        logo.pack(side="left")
        titles = tk.Frame(inner, bg=BRAND)
        titles.pack(side="left", padx=12)
        tk.Label(titles, text="HomeNet Monitor", bg=BRAND, fg="white", font=(FONT, 15, "bold")).pack(anchor="w")
        tk.Label(titles, text="Home network dashboard on this PC", bg=BRAND, fg="#dbe4ff", font=(FONT, 9)).pack(anchor="w")
        self.clock = tk.Label(inner, text="", bg=BRAND, fg="white", font=(FONT, 10, "bold"), justify="right")
        self.clock.pack(side="right")

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=16, pady=14)

        # HomeNet card
        self.hn = Card(wrap, "HomeNet", "Dashboard, device tracking, schedules and limits")
        self.hn.pack(fill="x")
        self.hn.link.bind("<Button-1>", lambda _e: core.open_dashboard())
        row = tk.Frame(self.hn.body, bg=CARD)
        row.pack(fill="x")
        self.hn_start = ttk.Button(row, text="▶  Start", style="Primary.TButton", command=lambda: self._homenet(core.start, self.open_after.get()))
        self.hn_stop = ttk.Button(row, text="■  Stop", style="Danger.TButton", command=lambda: self._homenet(core.stop))
        self.hn_restart = ttk.Button(row, text="↻  Restart", command=lambda: self._homenet(core.restart))
        for b in (self.hn_start, self.hn_stop, self.hn_restart):
            b.pack(side="left", padx=(0, 8))
        self.hn_open = ttk.Button(self.hn.body, text="Open dashboard in browser", style="Primary.TButton", command=core.open_dashboard)
        self.hn_open.pack(fill="x", pady=(10, 0))

        # AdGuard card
        self.ag = Card(wrap, "AdGuard Home", "DNS filtering. Devices use it to look up websites.")
        self.ag.pack(fill="x", pady=12)
        self.ag.link.bind("<Button-1>", lambda _e: self._open_adguard())
        row = tk.Frame(self.ag.body, bg=CARD)
        row.pack(fill="x")
        self.ag_start = ttk.Button(row, text="▶  Start", style="Primary.TButton", command=lambda: self._adguard("start"))
        self.ag_stop = ttk.Button(row, text="■  Stop", style="Danger.TButton", command=lambda: self._adguard("stop"))
        self.ag_restart = ttk.Button(row, text="↻  Restart", command=lambda: self._adguard("restart"))
        for b in (self.ag_start, self.ag_stop, self.ag_restart):
            b.pack(side="left", padx=(0, 8))
        self.ag_open = ttk.Button(self.ag.body, text="Open AdGuard Home in browser", style="Green.TButton", command=self._open_adguard)
        self.ag_open.pack(fill="x", pady=(10, 0))
        tk.Label(self.ag.body, text="Start/Stop/Restart ask for Windows admin permission. While stopped, devices that\n"
                                    "use this PC for DNS can't reach websites.", bg=CARD, fg=MUTED, font=(FONT, 8),
                 justify="left").pack(anchor="w", pady=(8, 0))

        # Options card
        opts = tk.Frame(wrap, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        opts.pack(fill="x")
        tk.Label(opts, text="Options", bg=CARD, fg=TEXT, font=(FONT, 11, "bold")).pack(anchor="w", padx=16, pady=(12, 4))
        self.startup = tk.BooleanVar(value=core.startup_enabled())
        ttk.Checkbutton(opts, text="Start HomeNet when Windows starts", variable=self.startup, style="Card.TCheckbutton",
                        command=self._toggle_startup).pack(anchor="w", padx=16)
        self.open_after = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Open the dashboard after starting HomeNet", variable=self.open_after,
                        style="Card.TCheckbutton").pack(anchor="w", padx=16, pady=(4, 12))

        # Footer
        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", side="bottom", padx=16, pady=(0, 14))
        ttk.Button(foot, text="Desktop shortcut", command=self._desktop).pack(side="left")
        ttk.Button(foot, text="View log", command=core.open_log).pack(side="left", padx=8)
        tk.Label(foot, text="Closing this window\nkeeps everything running.", bg=BG, fg=MUTED, font=(FONT, 8),
                 justify="right").pack(side="right")

    # ------------------------------------------------------------ status
    def _tick(self):
        self.clock.configure(text=time.strftime("%H:%M:%S\n%a %d %b"))
        self.after(1000, self._tick)

    def _poll(self):
        def check():
            hn = core.is_running()
            ag = core.adguard_service_state()
            web = core.adguard_web_ok() if ag == "running" else False
            self.after(0, lambda: self._show(hn, ag, web))
        threading.Thread(target=check, daemon=True).start()
        self.after(3000, self._poll)

    def _show(self, hn: bool, ag: str, web: bool):
        self.hn_running, self.ag_state = hn, ag
        if not self.busy["homenet"]:
            self.hn.set_state(GREEN if hn else RED, "Running" if hn else "Stopped", f"{core.dashboard_url()}  ↗" if hn else "")
            self._enable(self.hn_start, not hn)
            for b in (self.hn_stop, self.hn_restart, self.hn_open):
                self._enable(b, hn)
        if not self.busy["adguard"]:
            if ag == "running":
                colour, label = (GREEN, "Running") if web else (AMBER, "Running, page not answering")
            elif ag == "stopped":
                colour, label = RED, "Stopped"
            elif ag in ("starting", "stopping"):
                colour, label = AMBER, ag.capitalize() + "…"
            else:
                colour, label = GREY, "Not installed" if ag == "not installed" else "Unknown"
            url = core.adguard_url()
            self.ag.set_state(colour, label, f"{url}  ↗" if ag == "running" and url else "")
            self._enable(self.ag_start, ag == "stopped")
            self._enable(self.ag_stop, ag == "running")
            self._enable(self.ag_restart, ag == "running")
            self._enable(self.ag_open, ag == "running")

    @staticmethod
    def _enable(btn, on: bool):
        btn.state(["!disabled"] if on else ["disabled"])

    def _lock(self, which: str, label: str):
        self.busy[which] = True
        card = self.hn if which == "homenet" else self.ag
        card.set_state(AMBER, label)
        btns = (self.hn_start, self.hn_stop, self.hn_restart, self.hn_open) if which == "homenet" else \
               (self.ag_start, self.ag_stop, self.ag_restart, self.ag_open)
        for b in btns:
            self._enable(b, False)

    def _background(self, which: str, fn, after_ok=None):
        def work():
            try:
                fn()
                err = None
            except Exception as e:  # shown to the user
                err = str(e)

            def done():
                self.busy[which] = False
                if err:
                    messagebox.showerror("HomeNet", err, parent=self)
                elif after_ok:
                    after_ok()
                self._poll_once()
            self.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def _poll_once(self):
        def check():
            hn, ag = core.is_running(), core.adguard_service_state()
            web = core.adguard_web_ok() if ag == "running" else False
            self.after(0, lambda: self._show(hn, ag, web))
        threading.Thread(target=check, daemon=True).start()

    # ------------------------------------------------------------ actions
    def _homenet(self, fn, open_after: bool = False):
        if self.busy["homenet"]:
            return
        self._lock("homenet", {core.start: "Starting…", core.stop: "Stopping…", core.restart: "Restarting…"}[fn])
        opener = core.open_dashboard if open_after and fn in (core.start, core.restart) else None
        self._background("homenet", fn, opener)

    def _adguard(self, action: str):
        if self.busy["adguard"]:
            return
        if action in ("stop", "restart") and not messagebox.askyesno(
                "AdGuard Home",
                ("Stop AdGuard Home?\n\nDevices that use this PC for DNS won't be able to reach websites until "
                 "it's started again.") if action == "stop" else
                "Restart AdGuard Home?\n\nWebsites may not load for a few seconds while it restarts.", parent=self):
            return
        self._lock("adguard", {"start": "Starting…", "stop": "Stopping…", "restart": "Restarting…"}[action])
        self._background("adguard", lambda: core.adguard_service(action))

    def _open_adguard(self):
        try:
            core.open_adguard()
        except Exception as e:
            messagebox.showerror("HomeNet", str(e), parent=self)

    def _toggle_startup(self):
        want = self.startup.get()
        try:
            core.set_startup(want)
        except Exception as e:
            self.startup.set(not want)
            messagebox.showerror("HomeNet", str(e), parent=self)

    def _desktop(self):
        try:
            path = core.create_desktop_shortcut()
            messagebox.showinfo("HomeNet", f"Shortcut created:\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("HomeNet", str(e), parent=self)


if __name__ == "__main__":
    args = set(sys.argv[1:])
    Launcher(autostart="--autostart" in args, minimized="--minimized" in args).mainloop()
