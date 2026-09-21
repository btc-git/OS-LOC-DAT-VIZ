# -*- mode: python ; coding: utf-8 -*-

import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files


LICENSE_DISTRIBUTIONS = (
    'PyQt6',
    'PyQt6-Qt6',
    'PyQt6-sip',
    'pandas',
    'numpy',
    'python-dateutil',
    'six',
    'openpyxl',
    'et-xmlfile',
    'xlrd',
    'tzdata',
    'PyInstaller',
    'pyinstaller-hooks-contrib',
    'altgraph',
    'packaging',
    'pefile',
    'pywin32-ctypes',
    'setuptools',
)
LICENSE_FILE_PREFIXES = (
    'license', 'licence', 'copying', 'notice', 'copyright'
)


def collect_dependency_license_files():
    license_datas = []
    for distribution_name in LICENSE_DISTRIBUTIONS:
        try:
            package = distribution(distribution_name)
        except PackageNotFoundError as error:
            raise RuntimeError(
                f"Missing locked build dependency: {distribution_name}"
            ) from error

        package_license_files = [
            package_file
            for package_file in (package.files or [])
            if package_file.name.lower().startswith(LICENSE_FILE_PREFIXES)
        ]
        if not package_license_files:
            raise RuntimeError(
                f"No packaged license file found for {distribution_name}"
            )

        package_name = package.metadata['Name']
        package_directory = f"{package_name}-{package.version}"
        for package_file in package_license_files:
            source_path = Path(package.locate_file(package_file))
            if not source_path.is_file():
                raise RuntimeError(
                    f"License file for {distribution_name} is unavailable: "
                    f"{package_file}"
                )
            relative_path = Path(*package_file.parts)
            destination = (
                Path('Third-Party-Licenses')
                / package_directory
                / relative_path.parent
            )
            license_datas.append((str(source_path), str(destination)))

    python_license = next((
        Path(sys.base_prefix) / filename
        for filename in ('LICENSE.txt', 'LICENSE', 'LICENSE_PYTHON.txt')
        if (Path(sys.base_prefix) / filename).is_file()
    ), None)
    if python_license is None:
        raise RuntimeError("No CPython license file found for the build interpreter")
    python_version = '.'.join(str(part) for part in sys.version_info[:3])
    license_datas.append((
        str(python_license),
        f"Third-Party-Licenses/CPython-{python_version}",
    ))
    return license_datas

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
dependency_license_datas = collect_dependency_license_files()

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=xlrd_binaries,
    datas=[
        ('LICENSE', '.'),
        ('THIRD_PARTY_NOTICES.md', '.'),
    ] + collect_data_files('tzdata') + xlrd_datas + viewer_datas + dependency_license_datas,
    hiddenimports=xlrd_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'numba', 'jinja2'],
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
