Traffic Widget (Router SSH)

Overview
- Live down/up speed from your router interface via SSH.
- Persistent SSH session, background polling thread (no UI freezes).
- System tray with dynamic icon, tooltip, and quick actions (Windows-friendly).
- Units in KB/s or MB/s (bytes per second, 1024 base).
- One-file Windows EXE build via PyInstaller.

Requirements
- Python 3.9+ (for building/running from source)
- Packages: `paramiko`, `pystray`, `Pillow`
  - Install: `pip install -r requirements.txt`
  - Optional: `.env` support via `python-dotenv` (included in requirements)

Configuration (env vars)
- `ROUTER_HOST` (default `192.168.0.1`)
- `ROUTER_USER` (default `root`)
- `PASSWORD` or `SSH_KEY` (path to private key)
  - Leave `SSH_KEY` empty to use password-only. Do not set it to an empty string path.
- `INTERFACE` (e.g. `eth0.2`)
- `ROUTER_PORT` (default `22`)
- SSH tuning: `SSH_TIMEOUT`, `SSH_BANNER_TIMEOUT`, `SSH_AUTH_TIMEOUT` (all default `15`)
- SSH auth flags: `LOOK_FOR_KEYS` (`0`/`1`), `ALLOW_AGENT` (`0`/`1`)
- `POLL_INTERVAL` seconds (default `1.0`)
- `ALWAYS_ON_TOP` `1`/`0`
- `START_MINIMIZED` `1`/`0`
 - Optional second device (AP): `AP_HOST`, `AP_USER`, `AP_PASSWORD` or `AP_SSH_KEY` (for rebooting a separate WiFi AP)

Run from source
1) `pip install -r requirements.txt`
2) Create/edit `.env` in the project root (keys below)
3) `python traffic_widget.py`

Notes on tray icon and “near the time”
- Windows does not allow arbitrary text next to the clock. This app updates the tray icon itself with short numbers (e.g., `D:12K` / `U:1.2M`) and the tooltip shows full speeds. Pin the icon to always show for best visibility.

Build a Windows EXE
- Run: `build_exe.bat`
- Output will be at `dist/TrafficWidget.exe`

Notes on .env loading
- The app loads `.env` from the current working directory and from the folder containing the script/EXE.
- Environment variables from your OS take precedence over `.env` (no override).


Admin commands config (no .env)
- Commands are defined in `commands.json` (created at the project root). The app also ships with sensible built‑in defaults if the file is missing.
- Supported keys:
  - `reboot_router`, `restart_ap`, `reconnect_4g` (supports `{iface}` token), `restart_network`, `ap_cmd_reboot`.
- The app loads `commands.json` from the current working directory and from the folder containing the script/EXE. Edit this file to customize behavior per firmware.

Tray quick actions
- Right-click the tray icon to access actions. Commands execute over SSH and are best-effort. Customize via the env vars above to fit your firmware (OpenWrt, vendor OS, etc.).

Troubleshooting SSH
- If you see "Error reading SSH protocol banner", increase `SSH_BANNER_TIMEOUT` (e.g., 20–30) and verify `ROUTER_PORT` is correct.
- Some devices require user `admin` instead of `root`. Update `ROUTER_USER` accordingly.
- Disable key/agent probing to avoid delays: set `LOOK_FOR_KEYS=0` and `ALLOW_AGENT=0`.
