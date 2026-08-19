"""
Entry point for the packaged desktop build. Sets desktop-mode environment
variables before the app config loads, then runs the API in-process via
uvicorn — this is what PyInstaller bundles into the shipped executable.
"""
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    data_dir = Path(os.environ["APPDATA"]) / "VyaparPro"
else:
    data_dir = Path.home() / ".vyaparpro"
data_dir.mkdir(parents=True, exist_ok=True)

# Windowed builds (console=False in the .spec) have no real stdout/stderr —
# both are None, which crashes anything (like uvicorn's logging setup) that
# assumes a stream is always available. Route output to a log file instead,
# which also gives us something to inspect if the app misbehaves on a
# customer's machine where there's no console to see errors in.
if sys.stdout is None or sys.stderr is None:
    log_file = open(data_dir / "backend.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stdout or log_file
    sys.stderr = sys.stderr or log_file

if os.environ.get("DB_ENGINE", "sqlite") == "sqlite" or "DB_ENGINE" not in os.environ:
    import decimal
    import sqlite3
    sqlite3.register_adapter(decimal.Decimal, lambda d: float(d))

os.environ.setdefault("DB_ENGINE", "sqlite")
os.environ.setdefault("SQLITE_PATH", str(data_dir / "vyaparpro.db"))
os.environ.setdefault("APP_ENV", "production")
os.environ.setdefault("LICENSE_PUBLIC_KEY", "91fc41abe83f60e044cf820d68bf41bd4e55f292bf3cb881d3e1c9242673e75e")
os.environ.setdefault("LICENSE_SERVER_URL", "https://license.vyaparpro.in/api/v1")
print(f"[startup] LICENSE_PUBLIC_KEY in use: {os.environ['LICENSE_PUBLIC_KEY']}", flush=True)

import uvicorn  # noqa: E402 — must come after env vars are set
from app.main import app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info", use_colors=False)