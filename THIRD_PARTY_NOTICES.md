# Third-Party Notices

This inventory describes the components used by the pinned Windows build in
`requirements-build.txt`. The build copies the license files supplied by these
distributions into `Third-Party-Licenses` inside the packaged application, and
the application displays them through **Licenses & Third-Party Notices**.
Authoritative package license files control if this summary differs from them.

## Runtime Components

| Component | Version | Declared license | Project |
| --- | --- | --- | --- |
| CPython | 3.11.3 | PSF-2.0 | <https://www.python.org/> |
| PyQt6 | 6.11.0 | GPL-3.0-only | <https://www.riverbankcomputing.com/software/pyqt/> |
| Qt libraries (`PyQt6-Qt6`) | 6.11.2 | LGPL-3.0 | <https://www.qt.io/> |
| PyQt6-sip | 13.12.0 | BSD-2-Clause | <https://github.com/Python-SIP/sip> |
| pandas | 3.0.5 | BSD-3-Clause | <https://pandas.pydata.org/> |
| NumPy | 2.4.6 | BSD-3-Clause and bundled third-party terms | <https://numpy.org/> |
| openpyxl | 3.1.5 | MIT | <https://openpyxl.readthedocs.io/> |
| et-xmlfile | 2.0.0 | MIT | <https://foss.heptapod.net/openpyxl/et_xmlfile> |
| xlrd | 2.0.2 | BSD | <https://xlrd.readthedocs.io/> |
| tzdata | 2025.2 | Apache-2.0 and timezone-data terms | <https://github.com/python/tzdata> |
| python-dateutil | 2.9.0.post0 | Dual license; see packaged text | <https://github.com/dateutil/dateutil> |
| six | 1.17.0 | MIT | <https://github.com/benjaminp/six> |

The Windows build also packages the unmodified GeoLibre Desktop 3.0.0 portable
archive under the MIT License. Its source and notices are available from
<https://github.com/opengeos/GeoLibre>; the redistributed MIT text is stored in
`GeoLibre-Viewer/LICENSE-GeoLibre.txt`.

## Build Tooling

The release build uses PyInstaller 6.22.3 under GPL-2.0-or-later with its
bootloader exception. Its pinned helpers are pyinstaller-hooks-contrib 2026.7,
altgraph 0.17.5, packaging 26.3, pefile 2024.8.26, and pywin32-ctypes 0.2.3.
The environment also pins setuptools 65.5.1. Their supplied license files are
also collected into packaged builds.

OS-LOC-DAT-VIZ and its GeoLibre plugin are licensed under GNU GPL v3.0; see
`LICENSE`. This notice is informational and is not legal advice.