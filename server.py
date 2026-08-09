import asyncio
import io
import json
import logging
import os
import pathlib
import platform
import secrets
import socket
import sys
import time
from typing import Dict, Optional, Set
from urllib.parse import quote

from PIL import Image

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse, HTMLResponse

FROZEN = getattr(sys, "frozen", False)


def app_dir():
    if FROZEN:
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


def resource_dir():
    if FROZEN:
        return pathlib.Path(getattr(sys, "_MEIPASS", app_dir()))
    return pathlib.Path(__file__).resolve().parent


APP_DIR = app_dir()
TOKEN_FILE = APP_DIR / "rd_token"

try:
    from token_default import TOKEN as DEFAULT_TOKEN
except Exception:
    DEFAULT_TOKEN = None


def load_shared_token():
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
        return "change-me"


TOKEN = load_shared_token()

app = FastAPI(title="VinetMonitor")

clients: Dict[str, WebSocket] = {}
client_info: Dict[str, dict] = {}
viewers: Set[WebSocket] = set()
viewer_sub: Dict[WebSocket, Optional[str]] = {}

thumb_last: Dict[str, float] = {}
thumb_cache: Dict[str, bytes] = {}

THUMB_FPS = float(os.getenv("RD_THUMB_FPS", "2"))
THUMB_INTERVAL = 1.0 / max(1.0, THUMB_FPS)
THUMB_MAX_SIZE = int(os.getenv("RD_THUMB_MAX", "320"))
THUMB_QUALITY = int(os.getenv("RD_THUMB_QUALITY", "30"))


STATIC_DIR = resource_dir() / "static"

HOME_HTML = (STATIC_DIR / "home.html").read_text(encoding="utf-8")
VIEW_TEMPLATE = (STATIC_DIR / "view.html").read_text(encoding="utf-8")


def client_list_payload():
    return [
        {"id": cid, "info": client_info.get(cid, {})}
        for cid in clients
    ]


def server_info_payload():
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "?"
    return {
        "hostname": hostname,
        "ip": local_ip() or "?",
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "port": int(os.getenv("RD_PORT", "8000")),
    }


async def broadcast_json_to_viewers(payload: dict):
    dead = []
    for ws in list(viewers):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)

    for ws in dead:
        viewers.discard(ws)
        viewer_sub.pop(ws, None)


async def broadcast_client_list():
    await broadcast_json_to_viewers({
        "type": "client_list",
        "clients": client_list_payload()
    })


def build_packet(client_id: str, payload: bytes) -> Optional[bytes]:
    cid = client_id.encode("utf-8")
    if not cid or len(cid) > 255:
        return None
    return bytes([len(cid)]) + cid + payload


async def send_packet(ws: WebSocket, packet: bytes) -> bool:
    try:
        await ws.send_bytes(packet)
        return True
    except Exception:
        return False


def make_thumbnail(jpeg: bytes) -> Optional[bytes]:
    try:
        img = Image.open(io.BytesIO(jpeg))
        img.thumbnail((THUMB_MAX_SIZE, THUMB_MAX_SIZE))
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=THUMB_QUALITY)
        return buf.getvalue()
    except Exception:
        return None


async def broadcast_frame(client_id: str, jpeg: bytes):
    packet = build_packet(client_id, jpeg)
    if packet is None:
        return

    dead = []
    for ws in list(viewers):
        if viewer_sub.get(ws) != client_id:
            continue
        if not await send_packet(ws, packet):
            dead.append(ws)

    for ws in dead:
        viewers.discard(ws)
        viewer_sub.pop(ws, None)


async def broadcast_thumb(client_id: str, thumb: bytes):
    packet = build_packet(client_id, thumb)
    if packet is None:
        return

    dead = []
    for ws in list(viewers):
        if viewer_sub.get(ws) != "*":
            continue
        if not await send_packet(ws, packet):
            dead.append(ws)

    for ws in dead:
        viewers.discard(ws)
        viewer_sub.pop(ws, None)


async def handle_client_frame(client_id: str, jpeg: bytes):
    await broadcast_frame(client_id, jpeg)

    now = time.monotonic()
    if now - thumb_last.get(client_id, 0.0) < THUMB_INTERVAL:
        return
    thumb_last[client_id] = now

    thumb = await asyncio.to_thread(make_thumbnail, jpeg)
    if thumb is None:
        return

    thumb_cache[client_id] = thumb
    await broadcast_thumb(client_id, thumb)


@app.get("/", response_class=HTMLResponse)
async def index():
    page = HOME_HTML.replace("__RD_TOKEN__", json.dumps(TOKEN))
    page = page.replace("__SERVER_INFO_JSON__", json.dumps(server_info_payload()))
    return page


@app.get("/static/icon-server.png")
async def server_icon():
    return FileResponse(str(STATIC_DIR / "icon-server.png"), media_type="image/png")


@app.get("/view/{client_id}", response_class=HTMLResponse)
async def view_client(client_id: str):
    token_q = f"token={quote(TOKEN, safe='')}" if TOKEN else ""
    page = VIEW_TEMPLATE
    page = page.replace("__CLIENT_ID_JSON__", json.dumps(client_id))
    page = page.replace("__RD_TOKEN__", json.dumps(TOKEN))
    page = page.replace("${TOKEN_QUERY}", token_q)
    return page


@app.websocket("/ws/client")
async def ws_client(
    websocket: WebSocket,
    token: str = Query(None),
    client_id: str = Query(...)
):
    await websocket.accept()

    if token != TOKEN:
        await websocket.close(code=4001)
        return

    if len(client_id) > 60:
        await websocket.close(code=4003)
        return

    old = clients.get(client_id)
    if old is not None:
        try:
            await old.close(code=4000)
        except Exception:
            pass

    clients[client_id] = websocket
    await broadcast_client_list()

    try:
        while True:
            msg = await websocket.receive()

            if msg.get("type") == "websocket.disconnect":
                break

            if msg.get("text") is not None:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue

                mtype = data.get("type")

                if mtype == "info":
                    client_info[client_id] = data.get("info", {})
                    await broadcast_client_list()

                elif mtype in {"tasks_response", "apps_response", "kill_response", "power_response", "error", "pong"}:
                    data["client"] = client_id
                    await broadcast_json_to_viewers(data)

            elif msg.get("bytes") is not None:
                await handle_client_frame(client_id, msg["bytes"])

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("client ws error:", e)
    finally:
        if clients.get(client_id) is websocket:
            clients.pop(client_id, None)
            client_info.pop(client_id, None)
            thumb_last.pop(client_id, None)
            thumb_cache.pop(client_id, None)
            await broadcast_client_list()


@app.websocket("/ws/viewer")
async def ws_viewer(
    websocket: WebSocket,
    token: str = Query(None)
):
    await websocket.accept()

    if token != TOKEN:
        await websocket.close(code=4001)
        return

    viewers.add(websocket)
    viewer_sub[websocket] = None

    await websocket.send_json({
        "type": "client_list",
        "clients": client_list_payload()
    })

    try:
        while True:
            msg = await websocket.receive()

            if msg.get("type") == "websocket.disconnect":
                break

            if msg.get("text") is None:
                continue

            try:
                data = json.loads(msg["text"])
            except json.JSONDecodeError:
                continue

            action = data.get("action")
            cid = data.get("client")

            if action == "select":
                viewer_sub[websocket] = cid
                if cid == "*":
                    for c2, thumb in list(thumb_cache.items()):
                        packet = build_packet(c2, thumb)
                        if packet is None:
                            continue
                        if not await send_packet(websocket, packet):
                            break
                continue

            if action == "list_clients":
                await websocket.send_json({
                    "type": "client_list",
                    "clients": client_list_payload()
                })
                continue

            target = clients.get(cid)
            if target is None:
                await websocket.send_json({
                    "type": "error",
                    "message": "Client tidak ditemukan"
                })
                continue

            try:
                if action == "input":
                    payload = data.get("data", {})
                    if not isinstance(payload, dict):
                        continue
                    payload["type"] = "input"
                    await target.send_json(payload)

                elif action == "get_tasks":
                    await target.send_json({
                        "type": "get_tasks",
                        "req_id": data.get("req_id")
                    })

                elif action == "get_apps":
                    await target.send_json({
                        "type": "get_apps",
                        "req_id": data.get("req_id")
                    })

                elif action == "kill":
                    await target.send_json({
                        "type": "kill",
                        "pid": data.get("pid"),
                        "req_id": data.get("req_id")
                    })

                elif action in {"shutdown", "restart"}:
                    await target.send_json({
                        "type": action,
                        "req_id": data.get("req_id")
                    })

            except Exception as exc:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Gagal mengirim perintah: {exc}"
                })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("viewer ws error:", e)
    finally:
        viewers.discard(websocket)
        viewer_sub.pop(websocket, None)


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


class LanLogFilter(logging.Filter):
    lan_ip = None

    def filter(self, record):
        if isinstance(record.msg, str) and record.msg.startswith("Uvicorn running on ") and self.lan_ip:
            if isinstance(record.args, tuple) and len(record.args) == 3:
                if record.args[1] == "0.0.0.0":
                    record.args = (record.args[0], self.lan_ip, record.args[2])
        return True


if __name__ == "__main__":
    import socket
    import uvicorn

    lan_ip = local_ip()
    port = int(os.getenv("RD_PORT", "8000"))

    LanLogFilter.lan_ip = lan_ip

    log_config = uvicorn.config.LOGGING_CONFIG
    log_config.setdefault("filters", {})["lan"] = {"()": "__main__.LanLogFilter"}
    for handler in ("default", "access"):
        log_config["handlers"][handler].setdefault("filters", []).append("lan")

    if lan_ip:
        print(f"VinetMonitor server berjalan di http://{lan_ip}:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_config=log_config)




