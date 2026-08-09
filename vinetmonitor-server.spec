# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\AI WORKSPACE\\REMOTE\\server.py'],
    pathex=[],
    binaries=[],
    datas=[('D:\\AI WORKSPACE\\REMOTE\\static\\home.html', 'static'), ('D:\\AI WORKSPACE\\REMOTE\\static\\view.html', 'static'), ('D:\\AI WORKSPACE\\REMOTE\\static\\icon-server.png', 'static')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='vinetmonitor-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['D:\\AI WORKSPACE\\REMOTE\\icon-server.ico'],
)
