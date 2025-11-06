Internet Speed Widget (AP‑only)

Overview
- Live down/up speed by reading counters from your Access Point (AP) over SSH.
- Compact window with speeds and a 3‑color status dot (green/up, red/down, gray/unknown).
- Always‑on overlay bar you can drag near the taskbar; stays visible until you hide it.
- System tray icon with live short speeds and a simple menu.
- Portable Windows build (single EXE) + easy .env configuration.

Quick Start (Windows EXE)
- Get `dist/TrafficWidget.exe` and `dist/.env.example` from this repo.
- Copy `dist/.env.example` to `dist/.env` and set your AP SSH details:
  - `AP_HOST=192.168.1.1`
  - `AP_USER=admin`
  - `AP_PASSWORD=...`  (or set `AP_SSH_KEY` to a private key path)
  - `INTERFACE=auto`    (or set exact name like `unet0`, `br0`, `wwan0`)
- Run `dist/TrafficWidget.exe`.

Configuration (.env)
- `AP_HOST` `AP_USER` `AP_PASSWORD` `AP_SSH_KEY` `AP_PORT` (default 22)
- `INTERFACE` interface to monitor, or `auto` to pick the busiest on startup
- `POLL_INTERVAL` seconds (default 1.0)
- `ALWAYS_ON_TOP` 1/0, `START_MINIMIZED` 1/0, `TEXT_OVERLAY` 1/0

Features
- Overlay bar: Toggle via tray → “Toggle Overlay”. Stays visible until hidden or app exit.
- Tray icon: Shows short rates (K/M). Tooltip shows full rates. Menu → Show / Toggle Overlay / Exit.
- Status dot: Green when link up, red when down, gray when unknown (inferred up when traffic flows).

Build From Source (Windows)
1) Install Python 3.9+.
2) `pip install -r requirements.txt`
3) Create `.env` (or use `.env.example`) and run: `python traffic_widget.py`
4) To build the EXE: run `build_exe.bat` → `dist/TrafficWidget.exe`

Notes
- The app loads `.env` from the current folder and alongside the script/EXE.
- Ensure SSH is enabled on the AP and the chosen `INTERFACE` exists. If speeds show `--`, try a specific name like `unet0`, `br0`, or `unet0_1`.

