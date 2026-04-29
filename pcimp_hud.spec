# PyInstaller spec for PCIMP HUD overlay
# Run: pyinstaller pcimp_hud.spec

block_cipher = None

a = Analysis(
    ['overlay.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icon.png',    '.'),
        ('player.svg',  '.'),
        ('train.svg',   '.'),
        ('route.svg',   '.'),
        ('send.svg',    '.'),
        ('111.svg',     '.'),
    ],
    hiddenimports=['keyboard', 'requests', 'PyQt6'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='pcimp_hud',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # no console window — silent if double-clicked without --key=
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.png',     # exe icon = app icon
)
