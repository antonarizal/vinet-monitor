# VinetMonitor

Aplikasi remote-desktop control berbasis web. Server Python (FastAPI + WebSockets) menjadi hub yang menghosting UI web dan meneruskan frame serta perintah ke/dari mesin yang dikendalikan (agent).

## Fitur

- **Streaming layar real-time** ke browser (JPEG via WebSocket).
- **Kontrol mouse & keyboard** dari browser (koordinat dinormalisasi 0–1, dipetakan ke piksel absolut di sisi client).
- **Daftar client & thumbnail** live untuk memilih mesin tujuan.
- **Manajemen proses** (daftar tugas, kill proses) dan **daftar aplikasi terpasang** (dari registry Windows).
- **Perintah daya**: shutdown & restart mesin client.
- **Autentikasi token tunggal** yang dibagikan semua client dan viewer (tanpa sinkronisasi file).
- **Build mandiri** menjadi executable dengan PyInstaller (client & server).

## Arsitektur

- `server.py` — FastAPI hub yang menyajikan web UI dan meneruskan frame/perintah. Entry: `python server.py` (uvicorn, `0.0.0.0:8000`).
- `client.py` — agent mesin yang dikendalikan (target Windows): streaming frame JPEG, kendali mouse/keyboard via `pyautogui`, enumerasi/kill proses via `psutil`. Entry: `python client.py`. Saat dibekukan (exe windowed, `--noconsole`), berjalan di system tray via `pystray`; log ditulis ke `vinetmonitor-client.log` di samping exe.
- `build.py` — membuat token (atau memakai ulang), menulisnya ke `token_default.py`, lalu membangun `dist/vinetmonitor-client.exe`.
- `build_server.py` — membangun server sebagai executable mandiri. Jalankan di OS target (Windows/Linux) karena PyInstaller tidak cross-compile.
- `static/home.html` + `static/view.html` — UI yang disajikan FastAPI; teks dan pesan error berbahasa Indonesia.

## Persyaratan

- Python 3.10+ (proyek ini dikembangkan dengan Python 3.10.6 di `.venv`)
- Windows untuk menjalankan `client.py` dengan fitur kontrol penuh (pyautogui, kill proses, shutdown)

## Instalasi

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> `requirements.txt` tidak dipin (unpinned).

## Menjalankan

### Server

```powershell
python server.py
```

Buka `http://127.0.0.1:8000` (atau IP LAN server yang ditampilkan saat start). Server memakai port 8000 secara default (ubah lewat env `RD_PORT`).

### Client (mesin yang dikendalikan)

```powershell
python client.py --server <url/ip>
```

Contoh: `python client.py --server 192.168.1.10:8000`

Cara penentuan target server (prioritas tertinggi dulu):

1. Env var `RD_SERVER`
2. Argumen `--server <url/ip>` — hasilnya disimpan ke file `rd_server` dan dipakai ulang
3. File `rd_server` (jika ada)
4. Default `ws://127.0.0.1:8000/ws/client`

Host/`host:port` polos dinormalisasi otomatis: `ws://` ditambahkan jika belum ada, dan `/ws/client` ditambahkan jika tanpa path.

### Menonton

Buka `http://127.0.0.1:8000/view/<client_id>` di browser untuk streaming langsung. Token diinjeksikan otomatis ke halaman, jadi viewer tidak perlu konfigurasi manual.

## Membangun executable

### Client

```powershell
.venv\Scripts\python build.py
```

Menghasilkan `dist/vinetmonitor-client.exe` (windowed, tanpa console, tray icon).

### Server

```powershell
.venv\Scripts\python build_server.py
```

Menghasilkan `dist/vinetmonitor-server.exe` (Windows) atau `dist/vinetmonitor-server` (Linux).

> **Catatan:** token yang sama dibakar ke `token_default.py` oleh `build.py`/`build_server.py`, sehingga server dan client berbagi satu token tanpa perlu sinkronisasi file.

## Autentikasi

Semua endpoint memakai satu token bersama. Urutan resolusi (sama di `server.py` dan `client.py`):

1. Env var `RD_TOKEN`
2. `token_default.TOKEN` (dibakar saat build)
3. Terakhir: auto-generate dan simpan ke file `rd_token` (hanya jika tidak ada token yang dibakar)

Token salah → WS ditutup dengan code `4001`.

## Env vars (semua opsional)

| Variabel | Default | Keterangan |
| --- | --- | --- |
| `RD_TOKEN` | — | Token bersama server/client/viewer |
| `RD_SERVER` | — | Target server untuk client |
| `RD_CLIENT_ID` | — | ID client yang dipakai agent |
| `RD_FPS` | 10 | Frame rate streaming client |
| `RD_SCALE` | 0.5 | Skala tangkapan layar client |
| `RD_QUALITY` | 40 | Kualitas JPEG client |
| `RD_THUMB_FPS` | 2 | Frekuensi pembuatan thumbnail server |
| `RD_THUMB_MAX` | 320 | Ukuran maksimum thumbnail |
| `RD_THUMB_QUALITY` | 30 | Kualitas JPEG thumbnail |

## Protokol komunikasi

- **Frame (binary)**: `[1 byte panjang client_id][client_id bytes][JPEG bytes]`. Client mengirim JPEG sebagai pesan WS biner; server meneruskan ke viewer yang subscribe dan menyimpan thumbnail (Pillow, dijalankan di thread).
- **Kontrol (JSON)** dari viewer: `action` `select`, `list_clients`, `input`, `get_tasks`, `get_apps`, `kill`, `shutdown`, `restart`.
- **Balasan (JSON)** dari client: `info`, `tasks_response`, `apps_response`, `kill_response`, `power_response`, `error`, `pong`.
- Koordinat input viewer **dinormalisasi 0–1**; `client.py` memetakannya ke piksel absolut dengan `pyautogui.size()`.
- `shutdown`/`restart` menjalankan `shutdown /s|/r /f /t 0` dan butuh hak admin (selain itu gagal dengan "Access denied").
- Client menolak membunuh PID-nya sendiri dan butuh admin untuk membunuh proses sistem. Client auto-reconnect setiap 3 detik.

## Catatan pengembangan

- `static/*.html` dibaca ke memori saat import (`server.py`). Mengubahnya butuh restart server penuh, bukan reload.
- Setelah mengubah token, wajib rebuild + restart server (token dimuat saat import).
- Tidak ada tes otomatis. Verifikasi manual: jalankan server + client, buka `/view/<client_id>`.
