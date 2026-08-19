# Build with: pyinstaller vyaparpro.spec
block_cipher = None

from PyInstaller.utils.hooks import collect_submodules

hidden_imports = [
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "sqlalchemy.dialects.sqlite",
    "aiosqlite",
    "passlib.handlers.bcrypt",
    "jose.backends.cryptography_backend",
    "pyotp",
    "email_validator",
    "slowapi",
] + collect_submodules("reportlab.graphics.barcode")

a = Analysis(
    ["desktop_main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="vyaparpro-backend",
    console=False,
    onefile=True,
)