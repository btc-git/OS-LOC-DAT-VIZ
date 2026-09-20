# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, collect_data_files

xlrd_datas, xlrd_binaries, xlrd_hiddenimports = collect_all('xlrd')
if not xlrd_hiddenimports:
    raise RuntimeError(
        "xlrd is required to build XLS support. Install requirements with the Python interpreter running PyInstaller."
    )

viewer_datas = [
    ('GeoLibre-Viewer/geolibre-desktop-3.0.0-x64-portable.zip', 'GeoLibre-Viewer'),
    ('GeoLibre-Viewer/LICENSE-GeoLibre.txt', 'GeoLibre-Viewer'),
    ('GeoLibre-Plugin/plugin.json', 'GeoLibre-Plugin'),
    ('GeoLibre-Plugin/dist/index.js', 'GeoLibre-Plugin/dist'),
    ('GeoLibre-Plugin/dist/style.css', 'GeoLibre-Plugin/dist'),
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=xlrd_binaries,
    datas=[('LICENSE', '.')] + collect_data_files('tzdata') + xlrd_datas + viewer_datas,
    hiddenimports=xlrd_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'numba'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='OS-LocationDataVisualizer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='wifi_icon.ico',
    version='version_info.txt',
)
