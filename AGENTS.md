# AGENTS.md

Remote-desktop control app "VinetMonitor" (Python, FastAPI + WebSockets). No README, no tests, no linter/formatter config, not a git repo.

## Architecture

- `server.py` â€” FastAPI hub that hosts the web UI and relays frames/commands. Entry: `python server.py` (uvicorn, `0.0.0.0:8000`). Frozen-aware: `resource_dir()` resolves `static/` from `sys._MEIPASS` (bundled) when frozen, `APP_DIR` (next to the exe) is used for the writable `rd_token`.
- `client.py` â€” the controlled-machine agent (Windows-targeted): streams JPEG frames, drives mouse/keyboard via `pyautogui`, enumerates/kills processes via `psutil`. Run on the machine being controlled: `python client.py`. When frozen (exe, built windowed with `--noconsole`), it has no console/taskbar entry and runs in the system tray via `pystray` (menu: show console when running from source, open log, exit-with-confirmation); prints go to `vinetmonitor-client.log` next to the exe.
- `build.py` â€” generates (or reuses) a token, writes it to `token_default.py`, then builds `dist/vinetmonitor-client.exe` via PyInstaller (windowed, no console, icon from `icon-client.ico` generated from `static/icon-client.png`, which is also bundled as `static/icon-client.png` and used for the tray icon). Run with the venv python: `.venv\Scripts\python build.py`.
- `build_server.py` â€” builds the server as a standalone executable via PyInstaller (onefile, console kept). Bundles `static/home.html`, `static/view.html`, and `static/icon-server.png` into `static/`. Same token handling as `build.py`. Platform-agnostic: run on Windows to get `dist/vinetmonitor-server.exe`, run on Linux to get `dist/vinetmonitor-server` (PyInstaller does not cross-compile, so build on the target OS). Windows builds get `icon-server.ico` (auto-generated from `static/icon-server.png`). Run with the venv python: `.venv\Scripts\python build_server.py`.
- `static/home.html` + `static/view.html` â€” served by FastAPI; UI strings and errors are Indonesian.

## Gotchas

- **`static/*.html` are read into memory at import time** (`server.py:36-37`). Editing them requires a full server restart, not a reload.
- All endpoints authenticate with a single shared token. Resolution order (same in `server.py` and `client.py`): `RD_TOKEN` env â†’ `token_default.TOKEN` (baked at build time by `build.py`; identical on the server and inside the built exe, so all clients share one token with no file sync) â†’ last resort: auto-generate and persist to a shared `rd_token` file (only when no baked token exists). Wrong token â†’ WS closes with code `4001`. The token is injected into the served HTML pages (placeholder `__RD_TOKEN__`), so the browser viewer needs no manual config. Note: `server.py` loads the token at import time, so rebuild + server restart are required after a token change.
- Binary frame protocol: `[1-byte client_id length][client_id bytes][JPEG bytes]`. Client sends raw JPEG frames as binary WS messages; server relays to subscribed viewers and caches thumbnails (Pillow, run in a thread).
- Viewer (browser) sends JSON control messages (`action`: `select`, `list_clients`, `input`, `get_tasks`, `get_apps`, `kill`, `shutdown`, `restart`); client replies with JSON types `info`, `tasks_response`, `apps_response`, `kill_response`, `power_response`, `error`, `pong`. `shutdown`/`restart` run `shutdown /s|/r /f /t 0` on the client and need admin rights (else they fail with "Access denied"). `get_apps` enumerates installed applications from the Windows registry (`HKEY_LOCAL_MACHINE`/`HKEY_CURRENT_USER` `...\Uninstall` incl. WOW6432Node) and replies `apps_response` with a list of `{name, version, publisher, install_date}`.
- Viewer input coordinates are **normalized 0â€“1**; `client.py` maps them to absolute pixels with `pyautogui.size()`.
- Client refuses to kill its own PID and needs admin rights to kill system processes. It auto-reconnects every 3s.
- When frozen, `client.py` is built windowed (`--noconsole`) so there is no console window or taskbar entry; it runs a `pystray` tray icon in a daemon thread (menu: open log, exit-with-confirmation). `redirect_io()` points `stdout`/`stderr` at `vinetmonitor-client.log` next to the exe. Exiting is only possible via the tray "Keluar" item (with a confirmation dialog).
- `requirements.txt` is unpinned; `.venv` is Python 3.10.6.

## Client server config

`client.py` resolves its target server (highest priority first):
1. `RD_SERVER` env var.
2. `python client.py --server <url/ip>` (e.g. `--server 192.168.1.10:8000`); the resolved URL is saved to the `rd_server` file next to `client.py` and reused on later runs.
3. `rd_server` file (if present).
4. Default `ws://127.0.0.1:8000/ws/client`; this default is also persisted to the `rd_server` file on first run (if no other source configured), so the file is filled even without `--server`.

A bare host/`host:port` is auto-normalized: `ws://` is added if missing, and `/ws/client` is appended when no path is given.

## Env vars (all optional)

- Shared: `RD_TOKEN`
- Client: `RD_SERVER`, `RD_CLIENT_ID`, `RD_FPS` (10), `RD_SCALE` (0.5), `RD_QUALITY` (40)
- Server: `RD_THUMB_FPS` (2), `RD_THUMB_MAX` (320), `RD_THUMB_QUALITY` (30), `RD_CLIENT_TIMEOUT` (60; detik tanpa aktivitas sebelum client dianggap mati — di-sweep tiap 5 detik oleh task background via lifespan)

## Quick check after changes

- Server: `python server.py`; Client: `python client.py`. Open `http://127.0.0.1:8000/view/<client_id>` to verify streaming. There are no automated tests.





