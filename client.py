import argparse
import asyncio
import ctypes
import io
import json
import os
import pathlib
import platform
import secrets
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import quote, urlparse

import psutil
import pyautogui
import websockets
from PIL import ImageGrab

if sys.platform == "win32":
    try:
        import winreg
    except Exception:
        winreg = None

SERVER_DEFAULT = "ws://127.0.0.1:8000/ws/client"


def app_dir():
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


BASE_DIR = app_dir()
TOKEN_FILE = BASE_DIR / "rd_token"
SERVER_FILE = BASE_DIR / "rd_server"

_LOG_HANDLE = None


def redirect_io():
    global _LOG_HANDLE
    if not getattr(sys, "frozen", False):
        return
    try:
        _LOG_HANDLE = open(BASE_DIR / "vinetmonitor-client.log", "a", encoding="utf-8", buffering=1)
    except Exception:
        try:
            _LOG_HANDLE = open(os.devnull, "w")
        except Exception:
            return
    sys.stdout = _LOG_HANDLE
    sys.stderr = _LOG_HANDLE


redirect_io()

try:
    from token_default import TOKEN as DEFAULT_TOKEN
except Exception:
    DEFAULT_TOKEN = None


def normalize_server_url(value):
    v = str(value).strip()
    if not v:
        return None
    if v.startswith("http://"):
        v = "ws://" + v[len("http://"):]
    elif v.startswith("https://"):
        v = "wss://" + v[len("https://"):]
    elif not v.startswith(("ws://", "wss://")):
        v = "ws://" + v
    try:
        parts = urlparse(v)
        if parts.path in ("", "/"):
            v = v.rstrip("/") + "/ws/client"
    except Exception:
        pass
    return v


def resolve_server_url():
    env = os.getenv("RD_SERVER")
    if env:
        url = normalize_server_url(env)
        if url:
            return url

    try:
        parser = argparse.ArgumentParser(description="VinetMonitor Client")
        parser.add_argument("--server", help="URL/IP server, contoh: 192.168.1.10:8000")
        args, _ = parser.parse_known_args()
        if args.server:
            url = normalize_server_url(args.server)
            if url:
                SERVER_FILE.write_text(url, encoding="utf-8")
                return url
    except Exception:
        pass

    try:
        if SERVER_FILE.exists():
            url = normalize_server_url(SERVER_FILE.read_text(encoding="utf-8"))
            if url:
                return url
    except Exception:
        pass

    default_url = normalize_server_url(SERVER_DEFAULT)
    try:
        SERVER_FILE.write_text(default_url, encoding="utf-8")
    except Exception:
        pass
    return default_url


SERVER_URL = resolve_server_url()


def load_or_create_token():
    env_token = os.getenv("RD_TOKEN")
    if env_token:
        return env_token

    if DEFAULT_TOKEN and DEFAULT_TOKEN != "CHANGE_ME":
        return DEFAULT_TOKEN

    try:
        if TOKEN_FILE.exists():
            value = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if value:
                return value

        value = secrets.token_urlsafe(32)
        TOKEN_FILE.write_text(value, encoding="utf-8")
        return value
    except Exception:
        return secrets.token_urlsafe(32)


TOKEN = load_or_create_token()
CLIENT_ID = os.getenv("RD_CLIENT_ID", platform.node() or "windows-client")

FPS = float(os.getenv("RD_FPS", "10"))
SCALE = float(os.getenv("RD_SCALE", "0.5"))
QUALITY = int(os.getenv("RD_QUALITY", "40"))
CPU_REFRESH_SECONDS = 5

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

KEY_MAP = {
    "control": "ctrl",
    "meta": "winleft",
    "os": "winleft",
    "windows": "winleft",
    " ": "space",
    "escape": "esc",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "delete": "delete",
    "backspace": "backspace",
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "shift": "shift",
    "alt": "alt",
    "capslock": "capslock",
    "contextmenu": "apps",
    "printscreen": "printscreen",
    "pause": "pause",
    "numlock": "numlock",
}

for i in range(1, 13):
    KEY_MAP[f"f{i}"] = f"f{i}"


_proc_cache = {}
_proc_stats = []
_system_stats = {}


def get_info():
    try:
        w, h = pyautogui.size()
    except Exception:
        w = h = 0

    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "?"

    return {
        "hostname": platform.node(),
        "ip": ip,
        "os": platform.platform(),
        "user": os.getenv("USERNAME", os.getenv("USER", "?")),
        "screen": f"{w}x{h}",
        "python": platform.python_version(),
    }


def refresh_processes():
    global _proc_cache, _proc_stats, _system_stats

    total_cpu = psutil.cpu_percent(interval=None)
    alive = {}
    stats = []

    for proc in psutil.process_iter():
        pid = proc.pid
        p = _proc_cache.get(pid, proc)

        try:
            if not p.is_running():
                continue

            cpu = p.cpu_percent(interval=None)

            with p.oneshot():
                name = p.name()
                try:
                    user = p.username()
                except Exception:
                    user = ""

                mem = p.memory_info().rss / (1024 * 1024)

            alive[pid] = p
            stats.append({
                "pid": pid,
                "name": name,
                "user": user,
                "cpu": round(cpu, 1),
                "mem": round(mem, 1),
            })

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue

    stats.sort(key=lambda item: item["mem"], reverse=True)

    vm = psutil.virtual_memory()
    _system_stats = {
        "hostname": platform.node(),
        "os": platform.platform(),
        "cpu_percent": round(total_cpu, 1),
        "mem_percent": vm.percent,
        "mem_used_mb": round(vm.used / (1024 * 1024), 1),
        "mem_total_mb": round(vm.total / (1024 * 1024), 1),
    }

    _proc_cache = alive
    _proc_stats = stats


def build_tasks(req_id):
    if not _proc_stats:
        refresh_processes()

    return {
        "type": "tasks_response",
        "req_id": req_id,
        "system": _system_stats,
        "processes": _proc_stats[:200],
    }


UNINSTALL_ROOTS = [
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE,
     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER,
     r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]


def list_installed_apps():
    if sys.platform != "win32":
        return {"apps": [], "error": "Hanya didukung di Windows"}

    apps = {}
    for root, base in UNINSTALL_ROOTS:
        try:
            with winreg.OpenKey(root, base) as key:
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    try:
                        sub_name = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(key, sub_name) as sub:
                            try:
                                name, _ = winreg.QueryValueEx(sub, "DisplayName")
                            except OSError:
                                continue
                            if not name:
                                continue

                            def _q(k, v):
                                try:
                                    return winreg.QueryValueEx(k, v)[0]
                                except OSError:
                                    return None

                            apps[name] = {
                                "name": name,
                                "version": _q(sub, "DisplayVersion") or "",
                                "publisher": _q(sub, "Publisher") or "",
                                "install_date": _q(sub, "InstallDate") or "",
                            }
                    except OSError:
                        continue
        except OSError:
            continue

    result = sorted(apps.values(), key=lambda a: a["name"].lower())
    return {"apps": result, "error": None}


def kill_pid(pid):
    try:
        pid = int(pid)
    except Exception:
        return False, "PID tidak valid"

    if pid == os.getpid():
        return False, "Tidak bisa menghentikan agent sendiri"

    try:
        p = psutil.Process(pid)
        p.kill()
        p.wait(timeout=3)
        return True, ""
    except psutil.AccessDenied:
        return False, "Access denied. Jalankan client sebagai Administrator untuk proses sistem."
    except psutil.NoSuchProcess:
        return False, "Proses sudah tidak ada."
    except Exception as e:
        return False, str(e)


def do_power_action(action):
    if sys.platform != "win32":
        return False, "Hanya didukung di Windows"

    if action == "shutdown":
        cmd = "shutdown /s /f /t 0"
    elif action == "restart":
        cmd = "shutdown /r /f /t 0"
    else:
        return False, "Aksi tidak dikenal"

    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
    except Exception as e:
        return False, str(e)

    if result.returncode == 0:
        return True, ""

    err = (result.stderr or result.stdout or "").strip()
    if result.returncode == 5 or "access" in err.lower():
        return False, "Access denied. Jalankan client sebagai Administrator."
    return False, err or f"Gagal (kode {result.returncode})"


def capture_jpeg():
    img = ImageGrab.grab()

    if img.mode != "RGB":
        img = img.convert("RGB")

    if SCALE not in (1.0, 1):
        img = img.resize((
            max(1, int(img.width * SCALE)),
            max(1, int(img.height * SCALE))
        ))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=QUALITY)
    return buf.getvalue()


def norm_to_abs(nx, ny):
    try:
        nx = float(nx)
    except Exception:
        nx = 0.0

    try:
        ny = float(ny)
    except Exception:
        ny = 0.0

    nx = max(0.0, min(1.0, nx))
    ny = max(0.0, min(1.0, ny))

    w, h = pyautogui.size()
    return int(nx * (w - 1)), int(ny * (h - 1))


def map_key(key):
    if not key:
        return None
    k = str(key).lower()
    return KEY_MAP.get(k, k)


def handle_input(data):
    event = data.get("event")

    if event in {"move", "down", "up", "click", "doubleclick"}:
        x, y = norm_to_abs(data.get("x"), data.get("y"))

    if event == "move":
        pyautogui.moveTo(x, y)

    elif event == "down":
        pyautogui.mouseDown(button=data.get("button", "left"), x=x, y=y)

    elif event == "up":
        pyautogui.mouseUp(button=data.get("button", "left"), x=x, y=y)

    elif event == "click":
        pyautogui.click(button=data.get("button", "left"), x=x, y=y)

    elif event == "doubleclick":
        pyautogui.doubleClick(x=x, y=y)

    elif event == "scroll":
        pyautogui.scroll(int(data.get("amount", 0)))

    elif event == "keydown":
        key = map_key(data.get("key"))
        if key:
            pyautogui.keyDown(key)

    elif event == "keyup":
        key = map_key(data.get("key"))
        if key:
            pyautogui.keyUp(key)

    elif event == "type":
        pyautogui.write(str(data.get("text", "")), interval=0.02)


_CTRL_HANDLER = None
TRAY_ICON = None


def _console_window():
    if sys.platform != "win32":
        return 0
    return ctypes.windll.kernel32.GetConsoleWindow()


def hide_console():
    hwnd = _console_window()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0)


def show_console():
    hwnd = _console_window()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 5)


def ignore_console_close():
    global _CTRL_HANDLER
    if sys.platform != "win32":
        return
    if _CTRL_HANDLER is None:
        handler_type = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

        def _handler(ctrl_type):
            if ctrl_type == 2:
                return True
            return False

        _CTRL_HANDLER = handler_type(_handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_CTRL_HANDLER, True)


def confirm_exit():
    if sys.platform != "win32":
        return True
    try:
        result = ctypes.windll.user32.MessageBoxW(
            0,
            "Yakin ingin menutup VinetMonitor Client?\n"
            "Klien akan berhenti mengirim ke server.",
            "VinetMonitor Client",
            0x24,
        )
        return result == 6
    except Exception:
        return False


def on_exit(icon, item):
    if confirm_exit():
        os._exit(0)


def open_log():
    try:
        os.startfile(str(BASE_DIR / "vinetmonitor-client.log"))
    except Exception:
        pass


def set_tray_status(text):
    icon = TRAY_ICON
    if icon is not None:
        try:
            icon.title = text
        except Exception:
            pass


def icon_path():
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", BASE_DIR)
    else:
        base = BASE_DIR
    return pathlib.Path(base) / "static" / "icon-client.png"


def start_tray():
    global TRAY_ICON
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return None

    img = None
    try:
        img = Image.open(icon_path()).convert("RGBA")
        img = img.resize((64, 64), Image.LANCZOS)
    except Exception:
        pass

    if img is None:
        img = Image.new("RGB", (64, 64), "#1d4ed8")
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([10, 10, 54, 42], radius=4, outline="white", width=3)
        draw.line([24, 52, 40, 52], fill="white", width=3)
        draw.rectangle([15, 16, 49, 36], outline="white", width=2)
        draw.ellipse([26, 21, 38, 33], fill="white")

    menu_items = [
        pystray.MenuItem("VinetMonitor Client", None, enabled=False),
        pystray.Menu.SEPARATOR,
    ]
    if _console_window():
        menu_items.append(
            pystray.MenuItem("Tampilkan Console", lambda icon, item: show_console(), default=True)
        )
    else:
        menu_items.append(
            pystray.MenuItem("Buka Log", lambda icon, item: open_log(), default=True)
        )
    menu_items.append(pystray.MenuItem("Keluar", on_exit))

    TRAY_ICON = pystray.Icon("vinetmonitor-client", img, "VinetMonitor Client", pystray.Menu(*menu_items))
    threading.Thread(target=TRAY_ICON.run, daemon=True).start()
    return TRAY_ICON


def maybe_background():
    if not getattr(sys, "frozen", False):
        return
    if sys.platform != "win32":
        return
    ignore_console_close()
    hide_console()


async def stream_loop(ws):
    interval = 1.0 / max(1.0, FPS)

    while True:
        start = time.time()

        try:
            frame = await asyncio.to_thread(capture_jpeg)
            await ws.send(frame)
        except Exception as e:
            print("capture error:", e)

        elapsed = time.time() - start
        await asyncio.sleep(max(0, interval - elapsed))


async def cpu_loop():
    while True:
        try:
            await asyncio.to_thread(refresh_processes)
        except Exception as e:
            print("refresh proses gagal:", e)

        await asyncio.sleep(CPU_REFRESH_SECONDS)


async def command_loop(ws):
    async for raw in ws:
        if isinstance(raw, (bytes, bytearray)):
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        try:
            mtype = data.get("type")

            if mtype == "get_tasks":
                resp = await asyncio.to_thread(build_tasks, data.get("req_id"))
                await ws.send(json.dumps(resp))

            elif mtype == "get_apps":
                resp = await asyncio.to_thread(list_installed_apps)
                resp["type"] = "apps_response"
                resp["req_id"] = data.get("req_id")
                await ws.send(json.dumps(resp))

            elif mtype == "kill":
                ok, err = await asyncio.to_thread(kill_pid, data.get("pid"))
                await ws.send(json.dumps({
                    "type": "kill_response",
                    "req_id": data.get("req_id"),
                    "pid": data.get("pid"),
                    "ok": ok,
                    "error": err,
                }))

            elif mtype in {"shutdown", "restart"}:
                ok, err = await asyncio.to_thread(do_power_action, mtype)
                await ws.send(json.dumps({
                    "type": "power_response",
                    "req_id": data.get("req_id"),
                    "action": mtype,
                    "ok": ok,
                    "error": err,
                }))

            elif mtype == "input":
                await asyncio.to_thread(handle_input, data)

            elif mtype == "ping":
                await ws.send(json.dumps({"type": "pong"}))

        except Exception as e:
            try:
                await ws.send(json.dumps({
                    "type": "error",
                    "message": str(e)
                }))
            except Exception:
                pass


async def run():
    url = (
        f"{SERVER_URL}"
        f"?token={quote(TOKEN, safe='')}"
        f"&client_id={quote(CLIENT_ID, safe='')}"
    )

    print(f"[client] target server: {SERVER_URL}")
    print(f"[client] client_id    : {CLIENT_ID}")

    while True:
        try:
            async with websockets.connect(
                url,
                max_size=20 * 1024 * 1024,
                ping_interval=20
            ) as ws:
                print(f"[client] terhubung sebagai {CLIENT_ID}")
                set_tray_status(f"VinetMonitor Client - Terhubung ({CLIENT_ID})")

                await ws.send(json.dumps({
                    "type": "info",
                    "info": await asyncio.to_thread(get_info)
                }))

                await asyncio.to_thread(refresh_processes)

                tasks = [
                    asyncio.create_task(stream_loop(ws)),
                    asyncio.create_task(command_loop(ws)),
                    asyncio.create_task(cpu_loop()),
                ]

                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in pending:
                    task.cancel()

                await asyncio.gather(*pending, return_exceptions=True)

                for task in done:
                    exc = task.exception()
                    if exc:
                        print("[client] task error:", exc)

        except Exception as e:
            print("[client] koneksi error:", e)
            set_tray_status(f"VinetMonitor Client - Error: {e}")

        await asyncio.sleep(3)


if __name__ == "__main__":
    maybe_background()
    start_tray()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Client berhenti.")




