import os
import time
import threading
import tkinter as tk
from tkinter import messagebox
import fnmatch

# Load configuration from a .env file if present (CWD and alongside script/EXE)
try:
    from pathlib import Path
    import sys
    from dotenv import load_dotenv
    # Current working directory .env
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    # Alongside script or PyInstaller bundle
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    load_dotenv(dotenv_path=base_dir / ".env", override=False)
except Exception:
    pass


try:
    import paramiko
except ImportError:
    raise SystemExit("Missing dependency: paramiko. Install via 'pip install paramiko'.")

# Optional tray support
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    HAS_TRAY = True
except Exception:
    HAS_TRAY = False


"""AP-only configuration (router is ignored).

Set these in .env (dist/.env when running the EXE):
  AP_HOST, AP_USER, AP_PASSWORD/AP_SSH_KEY, INTERFACE (or INTERFACE=auto)
"""

# AP connection
AP_HOST = os.getenv("AP_HOST", os.getenv("ROUTER_HOST", "192.168.1.1"))
AP_USER = os.getenv("AP_USER", os.getenv("ROUTER_USER", "admin"))
AP_PASSWORD = os.getenv("AP_PASSWORD", os.getenv("PASSWORD", ""))
AP_SSH_KEY = (os.getenv("AP_SSH_KEY", os.getenv("SSH_KEY", "")) or None)
AP_PORT = int(os.getenv("AP_PORT", os.getenv("ROUTER_PORT", "22")))

# Monitoring
INTERFACE = os.getenv("INTERFACE", "auto").strip()  # "auto" picks the busiest iface on the AP
# When monitoring from the AP's LAN perspective, the data flowing "down" to clients
# is TX on the client-facing interface(s). Set LAN_PERSPECTIVE=1 to swap directions
# so Down=TX and Up=RX on the chosen interface/pattern.
LAN_PERSPECTIVE = os.getenv("LAN_PERSPECTIVE", "0") in ("1", "true", "True")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))  # seconds
ALWAYS_ON_TOP = os.getenv("ALWAYS_ON_TOP", "0") in ("1", "true", "True")
START_MINIMIZED = os.getenv("START_MINIMIZED", "0") in ("1", "true", "True")
TEXT_OVERLAY = os.getenv("TEXT_OVERLAY", "1") in ("1", "true", "True")


class APMonitor:
    def __init__(self, host, user, password=None, key_filename=None):
        self.host = host
        self.user = user
        self.password = password
        self.key_filename = key_filename
        self._ssh = None
        self._lock = threading.Lock()

    def connect(self):
        with self._lock:
            if self._ssh:
                return
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                self.host,
                port=AP_PORT,
                username=self.user,
                password=self.password,
                key_filename=self.key_filename,
                timeout=15,
                banner_timeout=15,
                auth_timeout=15,
                look_for_keys=False,
                allow_agent=False,
            )
            self._ssh = ssh

    def close(self):
        with self._lock:
            if self._ssh:
                try:
                    self._ssh.close()
                finally:
                    self._ssh = None

    def _ensure(self):
        if not self._ssh:
            self.connect()

    def read_counters(self, iface):
        """Return (rx_bytes, tx_bytes) for iface, or (None, None)."""
        self._ensure()
        with self._lock:
            _, stdout, _ = self._ssh.exec_command("cat /proc/net/dev 2>/dev/null || true")
            data = stdout.read().decode(errors="ignore")
        target = iface + ":"
        for line in data.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            name, rest = line.split(":", 1)
            if name.strip() != iface:
                continue
            parts = rest.split()
            if not parts:
                continue
            try:
                rx_bytes = int(parts[0])
                tx_bytes = int(parts[8]) if len(parts) > 8 else int(parts[-1])
                return rx_bytes, tx_bytes
            except Exception:
                continue
        return None, None

    def read_all_counters(self):
        """Return dict{name:(rx_bytes, tx_bytes)} parsed from /proc/net/dev (excludes 'lo')."""
        self._ensure()
        with self._lock:
            _, stdout, _ = self._ssh.exec_command("cat /proc/net/dev 2>/dev/null || true")
            data = stdout.read().decode(errors="ignore")
        result = {}
        for line in data.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            name, rest = line.split(":", 1)
            name = name.strip()
            if name == "lo":
                continue
            parts = rest.split()
            if len(parts) < 2:
                continue
            try:
                rx_bytes = int(parts[0])
                tx_bytes = int(parts[8]) if len(parts) > 8 else int(parts[-1])
                result[name] = (rx_bytes, tx_bytes)
            except Exception:
                continue
        return result

    def read_link_status(self, iface):
        """Return 'up', 'down', or 'unknown' for interface link status on the AP."""
        self._ensure()
        with self._lock:
            try:
                cmd = f"cat /sys/class/net/{iface}/operstate 2>/dev/null || true"
                _, stdout, _ = self._ssh.exec_command(cmd)
                s = stdout.read().decode(errors="ignore").strip().lower()
                if s in ("up", "down", "dormant", "unknown"):
                    return "up" if s == "up" else ("down" if s == "down" else "unknown")
            except Exception:
                pass
            try:
                cmd = f"ip link show {iface} 2>/dev/null || true"
                _, stdout, _ = self._ssh.exec_command(cmd)
                out = stdout.read().decode(errors="ignore")
                if " state UP" in out or "<UP," in out:
                    return "up"
                if " state DOWN" in out:
                    return "down"
            except Exception:
                pass
        return "unknown"


def format_rate_bytes_per_sec(bps):
    if bps is None:
        return "--"
    if bps >= 1024 * 1024:
        return f"{bps / (1024*1024):.2f} MB/s"
    return f"{bps / 1024:.0f} KB/s"


class App:
    def __init__(self):
        self.monitor = APMonitor(AP_HOST, AP_USER, AP_PASSWORD or None, AP_SSH_KEY)
        self.iface = INTERFACE

        # UI
        self.root = tk.Tk()
        self.root.title("Live Traffic (AP)")
        self.root.geometry("260x150")
        self.root.resizable(False, False)
        try:
            self.root.attributes("-topmost", ALWAYS_ON_TOP)
        except Exception:
            pass

        self.lbl_rx = tk.Label(self.root, text="Down: --", font=("Segoe UI", 14), fg="blue")
        self.lbl_tx = tk.Label(self.root, text="Up:   --", font=("Segoe UI", 14), fg="green")
        self.lbl_rx.pack(pady=(10, 2))
        self.lbl_tx.pack(pady=(0, 6))

        # Controls row (place early so it's always visible)
        controls = tk.Frame(self.root)
        controls.pack(pady=(0, 4))
        self.var_topmost = tk.BooleanVar(value=ALWAYS_ON_TOP)
        chk = tk.Checkbutton(
            controls,
            text="Always on top",
            variable=self.var_topmost,
            command=self.toggle_topmost,
            font=("Segoe UI", 9),
        )
        try:
            # Ensure text is visible on all themes
            chk.configure(fg="#000000", bg=self.root.cget("bg"), activeforeground="#000000", activebackground=self.root.cget("bg"))
        except Exception:
            pass
        chk.pack(side=tk.LEFT, padx=6)
        self._chk_topmost = chk

        # Connection status dot (gray unknown, green up, red down)
        self.status_dot = tk.Canvas(self.root, width=12, height=12, highlightthickness=0, bd=0)
        self._status_item = self.status_dot.create_oval(1, 1, 11, 11, fill="#999999", outline="")
        self.status_dot.pack(pady=(0, 6))

        # Connection error message (shown in red when SSH fails)
        self.lbl_err = tk.Label(self.root, text="", font=("Segoe UI", 10), fg="#e74c3c")
        self.lbl_err.pack(pady=(0, 4))

        

        # Tray icon
        self.tray = None
        if HAS_TRAY:
            self.tray = TrayManager(self.show_window, self.exit_app, on_toggle_overlay=self.toggle_overlay, on_toggle_topmost=self.toggle_topmost)
            self.tray.start(title="Traffic", down_text="--", up_text="--")

        # Overlay (persistent until explicitly hidden)
        self.overlay = TextOverlay(self.root)
        if TEXT_OVERLAY:
            try:
                self.overlay.show()
            except Exception:
                pass

        # State
        self.prev = None  # (rx, tx, t)
        self.lock = threading.Lock()
        self.down_bps = None
        self.up_bps = None
        self.link_status = "unknown"
        self.stop_event = threading.Event()
        self._error_shown = False
        self._last_error_text = ""

        # Start polling thread
        self.thread = threading.Thread(target=self.poll_loop, daemon=True)
        self.thread.start()

        if START_MINIMIZED:
            try:
                self.root.iconify()
            except Exception:
                pass

    def toggle_topmost(self):
        try:
            self.root.attributes("-topmost", self.var_topmost.get())
        except Exception:
            pass

    def update_ui(self):
        with self.lock:
            down = self.down_bps
            up = self.up_bps
            status = self.link_status
            last_err = self._last_error_text
        self.lbl_rx.config(text=f"Down: {format_rate_bytes_per_sec(down)}")
        self.lbl_tx.config(text=f"Up:   {format_rate_bytes_per_sec(up)}")
        # Status dot color
        color = "#2ecc71" if status == "up" else ("#e74c3c" if status == "down" else "#999999")
        try:
            self.status_dot.itemconfig(self._status_item, fill=color)
        except Exception:
            pass
        # Tray update
        if self.tray:
            try:
                self.tray.update(down or 0, up or 0)
            except Exception:
                pass
        # Overlay update (always update text; visibility controlled by user)
        try:
            dr = format_rate_bytes_per_sec(down)
            ur = format_rate_bytes_per_sec(up)
            pretty_status = {"up": "up", "down": "down"}.get(status, "unknown")
            if self.overlay:
                self.overlay.set_text(dr, ur, status_text=pretty_status)
        except Exception:
            pass
        # Error label
        try:
            self.lbl_err.config(text=last_err)
        except Exception:
            pass

    def poll_loop(self):
        next_time = time.perf_counter()
        # If INTERFACE is 'auto', detect the busiest iface on AP at startup
        if not self.iface or self.iface.lower() == "auto":
            try:
                first = self.monitor.read_all_counters()
                time.sleep(0.5)
                second = self.monitor.read_all_counters()
                best_name = None
                best_delta = -1
                for name, (rx1, tx1) in first.items():
                    rx2, tx2 = second.get(name, (rx1, tx1))
                    delta = max(rx2 - rx1, 0) + max(tx2 - tx1, 0)
                    if delta > best_delta:
                        best_delta = delta
                        best_name = name
                if best_name:
                    self.iface = best_name
                    try:
                        self.root.after(0, lambda: self.root.title(f"Live Traffic (AP:{self.iface})"))
                    except Exception:
                        pass
            except Exception:
                pass
        last_auto_check = time.monotonic()
        while not self.stop_event.is_set():
            try:
                # Support aggregation: if INTERFACE contains ',' or '*' then sum matching ifaces
                aggregate = ("," in self.iface) or ("*" in self.iface) or ("?" in self.iface)
                if aggregate:
                    allc = self.monitor.read_all_counters()
                    total_rx = total_tx = 0
                    for part in [p.strip() for p in self.iface.split(",") if p.strip()]:
                        for name, (arx, atx) in allc.items():
                            if fnmatch.fnmatchcase(name, part):
                                total_rx += arx
                                total_tx += atx
                    rx, tx = total_rx, total_tx
                else:
                    rx, tx = self.monitor.read_counters(self.iface)
                status = self.monitor.read_link_status(self.iface)
                now = time.time()
                if rx is not None and tx is not None:
                    # Clear any previous error state
                    if self._last_error_text:
                        self._last_error_text = ""
                        self._error_shown = False
                    if self.prev is not None:
                        prx, ptx, pt = self.prev
                        dt = max(now - pt, 1e-6)
                        drx = rx - prx
                        dtx = tx - ptx
                        if drx < 0 or dtx < 0:
                            drx = dtx = 0
                        # Map down/up depending on perspective
                        if LAN_PERSPECTIVE:
                            down_bps = dtx / dt  # AP transmits to clients
                            up_bps = drx / dt    # AP receives from clients
                        else:
                            down_bps = drx / dt  # RX from WAN
                            up_bps = dtx / dt
                        if status not in ("up", "down") and (down_bps > 0 or up_bps > 0):
                            status = "up"
                        with self.lock:
                            self.down_bps = down_bps
                            self.up_bps = up_bps
                            self.link_status = status or "unknown"
                        try:
                            self.root.after(0, self.update_ui)
                        except Exception:
                            pass
                    self.prev = (rx, tx, now)

                    # Periodic dynamic auto-detect: if speeds are very low but another iface is busy, switch
                    if (time.monotonic() - last_auto_check) > 5.0:
                        try:
                            all1 = self.monitor.read_all_counters()
                            time.sleep(0.25)
                            all2 = self.monitor.read_all_counters()
                            best_name = None
                            best_delta = -1
                            for name, (r1, t1) in all1.items():
                                r2, t2 = all2.get(name, (r1, t1))
                                d = max(r2 - r1, 0) + max(t2 - t1, 0)
                                if d > best_delta:
                                    best_delta = d
                                    best_name = name
                            # if current aggregate not used and observed delta is tiny while another iface busy -> switch
                            current_delta = (drx + dtx)
                            if not aggregate and best_name and best_delta > max(current_delta * 4, 200*1024):
                                self.iface = best_name
                                self.prev = None
                                try:
                                    self.root.after(0, lambda: self.root.title(f"Live Traffic (AP:{self.iface})"))
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        last_auto_check = time.monotonic()
            except Exception as e:
                try:
                    self.monitor.close()
                except Exception:
                    pass
                # Record and notify error once
                msg = str(e) or "SSH connection failed"
                self._last_error_text = f"Connection failed: {msg}"
                if not self._error_shown:
                    try:
                        messagebox.showerror("Connection failed", self._last_error_text)
                    except Exception:
                        pass
                    self._error_shown = True
            next_time += POLL_INTERVAL
            time.sleep(max(0.0, next_time - time.perf_counter()))

    def exit_app(self):
        try:
            self.stop_event.set()
            if self.tray:
                try:
                    self.tray.stop()
                except Exception:
                    pass
            self.monitor.close()
        finally:
            try:
                self.root.destroy()
            except Exception:
                pass

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray if self.tray else self.exit_app)
        self.root.mainloop()

    def show_window(self):
        try:
            self.root.deiconify()
            self.root.after(0, self.root.lift)
        except Exception:
            pass

    def minimize_to_tray(self):
        if self.tray:
            try:
                self.root.withdraw()
            except Exception:
                pass
        else:
            try:
                self.root.iconify()
            except Exception:
                pass

    def toggle_overlay(self):
        try:
            if self.overlay and self.overlay.visible():
                self.overlay.hide()
            else:
                self.overlay.show()
        except Exception:
            pass


# Minimal tray manager to show live speeds and menu
class TrayManager:
    def __init__(self, on_show, on_exit, on_toggle_overlay=None, on_toggle_topmost=None):
        self.on_show = on_show
        self.on_exit = on_exit
        self.on_toggle_overlay = on_toggle_overlay
        self.on_toggle_topmost = on_toggle_topmost
        self.icon = None
        self._thread = None

    def _make_image(self, down_text, up_text):
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
        draw.rounded_rectangle([0, 0, 31, 31], radius=6, fill=(32, 32, 32, 240))
        draw.text((3, 4), "D:", fill=(100, 160, 255, 255), font=font)
        draw.text((3, 16), "U:", fill=(120, 220, 120, 255), font=font)
        draw.text((14, 4), down_text, fill=(220, 220, 220, 255), font=font)
        draw.text((14, 16), up_text, fill=(220, 220, 220, 255), font=font)
        return img

    def start(self, title="Traffic", down_text="--", up_text="--"):
        if not HAS_TRAY:
            return
        image = self._make_image(down_text, up_text)
        items = [pystray.MenuItem("Show", lambda: self.on_show())]
        if self.on_toggle_overlay:
            items.append(pystray.MenuItem("Toggle Overlay", lambda: self.on_toggle_overlay()))
        if self.on_toggle_topmost:
            items.append(pystray.MenuItem("Toggle Always On Top", lambda: self.on_toggle_topmost()))
        items.append(pystray.MenuItem("Exit", lambda: self.on_exit()))
        menu = pystray.Menu(*items)
        self.icon = pystray.Icon("traffic_widget", image, title, menu)

        def run():
            try:
                self.icon.run()
            except Exception:
                pass
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def update(self, down_bytes_per_s, up_bytes_per_s):
        if not HAS_TRAY or not self.icon:
            return
        def short(v):
            if v is None:
                return "--"
            if v >= 1024 * 1024:
                return f"{v/(1024*1024):.1f}M"
            return f"{max(v/1024, 0):.0f}K"
        d = short(down_bytes_per_s)
        u = short(up_bytes_per_s)
        try:
            self.icon.title = f"Down: {format_rate_bytes_per_sec(down_bytes_per_s)} | Up: {format_rate_bytes_per_sec(up_bytes_per_s)}"
            self.icon.icon = self._make_image(d, u)
        except Exception:
            pass

    def stop(self):
        if not HAS_TRAY or not self.icon:
            return
        try:
            self.icon.stop()
        except Exception:
            pass


class TextOverlay:
    def __init__(self, root):
        self.root = root
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        try:
            self.top.attributes("-topmost", True)
        except Exception:
            pass
        self.bg = "#202020"
        self.top.configure(bg=self.bg)
        # Row with dot + text
        self.row = tk.Frame(self.top, bg=self.bg)
        self.row.pack(ipadx=8, ipady=4)
        self.dot = tk.Canvas(self.row, width=10, height=10, highlightthickness=0, bg=self.bg, bd=0)
        self._dot_item = self.dot.create_oval(1, 1, 9, 9, fill="#999999", outline="")
        self.text = tk.Label(self.row, text="Down: -- | Up: --", fg="#FFFFFF", bg=self.bg, font=("Segoe UI", 11))
        self.dot.pack(side=tk.LEFT, padx=(0, 6))
        self.text.pack(side=tk.LEFT)
        # Drag behavior
        self._drag = None
        for w in (self.row, self.dot, self.text):
            try:
                w.bind("<ButtonPress-1>", self._on_press)
                w.bind("<B1-Motion>", self._on_drag)
                w.bind("<ButtonRelease-1>", self._on_release)
            except Exception:
                pass
        # Place bottom-right initially
        try:
            self.top.update_idletasks()
            sw = self.top.winfo_screenwidth()
            sh = self.top.winfo_screenheight()
            w = self.top.winfo_width()
            h = self.top.winfo_height()
            x = max(sw - w - 8, 0)
            y = max(sh - h - 8, 0)
            self.top.geometry(f"+{x}+{y}")
        except Exception:
            pass
        self._visible = False
        # Intercept close to hide instead of destroy
        try:
            self.top.protocol("WM_DELETE_WINDOW", self.hide)
        except Exception:
            pass

    def _on_press(self, event):
        self._drag = (event.x_root, event.y_root)

    def _on_drag(self, event):
        if not self._drag:
            return
        dx = event.x_root - self._drag[0]
        dy = event.y_root - self._drag[1]
        self._drag = (event.x_root, event.y_root)
        x = self.top.winfo_x() + dx
        y = self.top.winfo_y() + dy
        self.top.geometry(f"+{x}+{y}")

    def _on_release(self, _):
        self._drag = None

    def show(self):
        try:
            self.top.deiconify()
            self.top.lift()
            try:
                self.top.attributes("-topmost", True)
            except Exception:
                pass
            self._visible = True
        except Exception:
            pass

    def hide(self):
        try:
            self.top.withdraw()
            self._visible = False
        except Exception:
            pass

    def visible(self):
        return bool(self._visible)

    def set_text(self, down_text, up_text, status_text="unknown"):
        try:
            self.text.config(text=f"Down: {down_text} | Up: {up_text}")
            color = "#2ecc71" if status_text == "up" else ("#e74c3c" if status_text == "down" else "#999999")
            self.dot.itemconfig(self._dot_item, fill=color)
        except Exception:
            pass


if __name__ == "__main__":
    app = App()
    app.run()
