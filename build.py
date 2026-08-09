import os
import pathlib
import secrets
import subprocess
import sys

BASE_DIR = pathlib.Path(__file__).resolve().parent


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


def main():
    token = os.getenv("RD_TOKEN") or existing_token() or secrets.token_urlsafe(32)

    (BASE_DIR / "token_default.py").write_text(
        f'TOKEN = "{token}"\n',
        encoding="utf-8",
    )
    print(f"token_default.py ditulis. Token: {token}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name",
        "vinetmonitor-client",
        "--icon",
        str(BASE_DIR / "icon-client.ico"),
        "--add-data",
        f"{str(BASE_DIR / 'static' / 'icon-client.png')};static",
        "--clean",
        str(BASE_DIR / "client.py"),
    ]
    subprocess.run(cmd, check=True, cwd=BASE_DIR)
    print("Build selesai: dist/vinetmonitor-client.exe")


if __name__ == "__main__":
    main()




