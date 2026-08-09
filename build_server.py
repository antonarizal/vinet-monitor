import os
import pathlib
import secrets
import subprocess
import sys

BASE_DIR = pathlib.Path(__file__).resolve().parent
IS_WINDOWS = sys.platform == "win32"


def existing_token():
    path = BASE_DIR / "token_default.py"
    if not path.exists():
        return None
    try:
        ns = {}
        exec(path.read_text(encoding="utf-8"), ns)
        token = ns.get("TOKEN")
        if token and token != "CHANGE_ME":
            return token
    except Exception:
        pass
    return None


def ensure_server_icon():
    ico = BASE_DIR / "icon-server.ico"
    if ico.exists():
        return ico
    png = BASE_DIR / "static" / "icon-server.png"
    if not png.exists():
        return None
    try:
        from PIL import Image
        img = Image.open(str(png)).convert("RGBA")
        img.save(str(ico), format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    except Exception:
        return None
    return ico


def main():
    token = os.getenv("RD_TOKEN") or existing_token() or secrets.token_urlsafe(32)

    (BASE_DIR / "token_default.py").write_text(
        f'TOKEN = "{token}"\n',
        encoding="utf-8",
    )
    print(f"token_default.py ditulis. Token: {token}")

    sep = ";" if IS_WINDOWS else ":"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "vinetmonitor-server",
        "--add-data",
        f"{str(BASE_DIR / 'static' / 'home.html')}{sep}static",
        "--add-data",
        f"{str(BASE_DIR / 'static' / 'view.html')}{sep}static",
        "--add-data",
        f"{str(BASE_DIR / 'static' / 'icon-server.png')}{sep}static",
        "--clean",
        str(BASE_DIR / "server.py"),
    ]

    if IS_WINDOWS:
        ico = ensure_server_icon()
        if ico is not None:
            cmd.insert(cmd.index("--clean"), "--icon")
            cmd.insert(cmd.index("--clean"), str(ico))

    subprocess.run(cmd, check=True, cwd=BASE_DIR)

    ext = ".exe" if IS_WINDOWS else ""
    print(f"Build selesai: dist/vinetmonitor-server{ext}")


if __name__ == "__main__":
    main()
