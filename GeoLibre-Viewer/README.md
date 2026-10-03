# Bundled GeoLibre Viewer

The Windows build packages the unmodified GeoLibre Desktop 3.0.0 x64 portable
archive for the **Process and Open in Viewer** and standalone **Open Viewer**
workflows.

- Upstream project: <https://github.com/opengeos/GeoLibre>
- Version: `3.0.0`
- Archive: `geolibre-desktop-3.0.0-x64-portable.zip`
- SHA-256: `b735fbc284e10f880c736689c29d3eae09c163fbf9bce20a530a11d9125d3519`
- License: MIT; see `LICENSE-GeoLibre.txt`

The application verifies the archive hash before extracting it into its own
per-user runtime directory. It installs the OS-LOC viewer plugin in GeoLibre's
standard per-user plugin directory. Simplified chrome is enabled by generated
OS-LOC companion projects and by the clean project used for reviewing existing
KML or GeoJSON files.

Generated viewer projects use the OpenFreeMap Liberty basemap. Loading that
basemap requires a network connection and discloses ordinary tile-request
metadata, including IP address and viewed map area, to OpenFreeMap. Local
source-record processing and export do not imply offline basemap viewing.