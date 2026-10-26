# -*- mode: python ; coding: utf-8 -*-
import os
import customtkinter

block_cipher = None

ctk_path = os.path.dirname(customtkinter.__file__)

added_datas = [
    ('images', 'images'),
    (ctk_path, 'customtkinter'),
]

a = Analysis(
    ['main_window.py'],
    pathex=['.'],
    binaries=[],
    datas=added_datas,
    hiddenimports=[
        'customtkinter',
        'PIL',
        'PIL.Image',
        'watchdog',
        'watchdog.observers',
        'watchdog.observers.polling',
        'watchdog.events',
        'pystray',
        'pystray._win32',
        'darkdetect',
        'paramiko',
        'scp',
        'ftplib',
        'argon2',
        'argon2.low_level',
        'ssh_keys',
    ],
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
    name='Statoris_Sync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='images/favicon.ico',
)
