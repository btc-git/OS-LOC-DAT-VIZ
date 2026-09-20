"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal


GEOLIBRE_VERSION = "3.0.0"
GEOLIBRE_ARCHIVE_NAME = "geolibre-desktop-3.0.0-x64-portable.zip"
GEOLIBRE_ARCHIVE_SHA256 = "b735fbc284e10f880c736689c29d3eae09c163fbf9bce20a530a11d9125d3519"
GEOLIBRE_EXECUTABLE_NAME = "geolibre-desktop.exe"
GEOLIBRE_APP_ID = "org.geolibre.desktop"
VIEWER_PLUGIN_ID = "osloc-dat-viz-viewer"
_viewer_process = None


class GeoLibreLaunchError(RuntimeError):
    """Raised when the bundled GeoLibre viewer cannot be prepared or started."""


def bundled_resource_path(relative_path):
    """Resolve a resource in a source checkout or a frozen PyInstaller app."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / relative_path


def default_runtime_root():
    """Return the per-user directory owned by the bundled viewer integration."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base_path = Path(local_app_data)
    else:
        base_path = Path.home() / "AppData" / "Local"
    return base_path / "OpenSource" / "LocationDataVisualizer" / "GeoLibreViewer"


def default_geolibre_data_root():
    """Return the same per-user roaming data directory GeoLibre resolves."""
    if sys.platform == "win32":
        try:
            import ctypes

            path_buffer = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.shell32.SHGetFolderPathW(
                None, 0x001A, None, 0, path_buffer
            ) == 0:
                return Path(path_buffer.value) / GEOLIBRE_APP_ID
        except (AttributeError, OSError):
            pass

    roaming_app_data = os.environ.get("APPDATA")
    if roaming_app_data:
        return Path(roaming_app_data) / GEOLIBRE_APP_ID
    return Path.home() / "AppData" / "Roaming" / GEOLIBRE_APP_ID


def calculate_sha256(file_path):
    """Calculate a file digest without loading the entire file into memory."""
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract_zip(archive_path, destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            member_path = Path(member.filename.replace("\\", "/"))
            if member_path.is_absolute() or ".." in member_path.parts:
                raise GeoLibreLaunchError(
                    f"Bundled GeoLibre archive contains an unsafe path: {member.filename}"
                )
            resolved_target = (destination / member_path).resolve()
            if destination != resolved_target and destination not in resolved_target.parents:
                raise GeoLibreLaunchError(
                    f"Bundled GeoLibre archive escapes its install directory: {member.filename}"
                )

        archive.extractall(destination)


def _install_geolibre_license(resource_root, install_path):
    license_source = Path(resource_root) / "GeoLibre-Viewer" / "LICENSE-GeoLibre.txt"
    if not license_source.is_file():
        raise GeoLibreLaunchError(f"Bundled GeoLibre license is missing: {license_source}")
    license_destination = Path(install_path) / "LICENSE-GeoLibre.txt"
    if (
        not license_destination.is_file()
        or license_destination.read_bytes() != license_source.read_bytes()
    ):
        shutil.copy2(license_source, license_destination)


def ensure_geolibre_installed(runtime_root=None, resource_root=None):
    """Extract the pinned portable GeoLibre build once and return its executable."""
    runtime_root = Path(runtime_root) if runtime_root else default_runtime_root()
    resource_root = Path(resource_root) if resource_root else bundled_resource_path("")
    install_path = runtime_root / "app" / GEOLIBRE_VERSION
    ready_marker = install_path / ".ready"

    if ready_marker.is_file():
        marker_value = ready_marker.read_text(encoding="utf-8").strip()
        relative_executable = Path(marker_value)
        executable_path = (install_path / relative_executable).resolve()
        if (
            not relative_executable.is_absolute()
            and ".." not in relative_executable.parts
            and executable_path.name.lower() == GEOLIBRE_EXECUTABLE_NAME
            and install_path.resolve() in executable_path.parents
            and executable_path.is_file()
        ):
            _install_geolibre_license(resource_root, install_path)
            return executable_path

    archive_path = resource_root / "GeoLibre-Viewer" / GEOLIBRE_ARCHIVE_NAME
    if not archive_path.is_file():
        raise GeoLibreLaunchError(
            f"Bundled GeoLibre archive is missing: {archive_path}"
        )
    if calculate_sha256(archive_path).lower() != GEOLIBRE_ARCHIVE_SHA256:
        raise GeoLibreLaunchError("Bundled GeoLibre archive failed its integrity check")

    staging_path = install_path.with_name(f"{install_path.name}.extracting")
    shutil.rmtree(staging_path, ignore_errors=True)
    staging_path.mkdir(parents=True, exist_ok=True)

    try:
        _safe_extract_zip(archive_path, staging_path)
        executable_matches = list(staging_path.rglob(GEOLIBRE_EXECUTABLE_NAME))
        if len(executable_matches) != 1:
            raise GeoLibreLaunchError(
                "Bundled GeoLibre archive does not contain exactly one expected executable"
            )
        relative_executable = executable_matches[0].relative_to(staging_path)
        (staging_path / ".ready").write_text(
            relative_executable.as_posix(), encoding="utf-8"
        )

        install_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(install_path, ignore_errors=True)
        staging_path.replace(install_path)
    except Exception:
        shutil.rmtree(staging_path, ignore_errors=True)
        raise

    _install_geolibre_license(resource_root, install_path)
    return (install_path / relative_executable).resolve()


def _build_plugin_archive(plugin_root):
    plugin_root = Path(plugin_root)
    manifest_path = plugin_root / "plugin.json"
    if not manifest_path.is_file():
        raise GeoLibreLaunchError(f"Bundled viewer plugin is missing: {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GeoLibreLaunchError(f"Bundled viewer plugin manifest is invalid: {error}") from error

    if manifest.get("id") != VIEWER_PLUGIN_ID:
        raise GeoLibreLaunchError("Bundled viewer plugin has an unexpected identifier")

    required_files = ["plugin.json", manifest.get("entry"), manifest.get("style")]
    if any(not file_name for file_name in required_files):
        raise GeoLibreLaunchError("Bundled viewer plugin manifest is incomplete")

    license_path = plugin_root / "LICENSE"
    if not license_path.is_file():
        license_path = plugin_root.parent / "LICENSE"
    if not license_path.is_file():
        raise GeoLibreLaunchError("Bundled viewer plugin GPL license is missing")

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_name in required_files:
            source_path = plugin_root / file_name
            if not source_path.is_file():
                raise GeoLibreLaunchError(
                    f"Bundled viewer plugin file is missing: {source_path}"
                )
            archive.write(source_path, Path(file_name).as_posix())
        archive.write(license_path, "LICENSE")
    return archive_buffer.getvalue()


def provision_geolibre_integration(resource_root=None, geolibre_data_root=None):
    """Install the current viewer plugin where GeoLibre scans at startup."""
    resource_root = Path(resource_root) if resource_root else bundled_resource_path("")
    geolibre_data_root = (
        Path(geolibre_data_root) if geolibre_data_root else default_geolibre_data_root()
    )
    plugins_path = geolibre_data_root / "plugins"
    plugins_path.mkdir(parents=True, exist_ok=True)

    plugin_bytes = _build_plugin_archive(resource_root / "GeoLibre-Plugin")
    plugin_path = plugins_path / f"{VIEWER_PLUGIN_ID}.zip"
    if not plugin_path.is_file() or plugin_path.read_bytes() != plugin_bytes:
        temporary_plugin_path = plugin_path.with_suffix(".zip.tmp")
        temporary_plugin_path.write_bytes(plugin_bytes)
        temporary_plugin_path.replace(plugin_path)
    return plugin_path


def _iter_coordinate_pairs(value):
    if not isinstance(value, (list, tuple)):
        return
    if (
        len(value) >= 2
        and isinstance(value[0], (int, float))
        and not isinstance(value[0], bool)
        and isinstance(value[1], (int, float))
        and not isinstance(value[1], bool)
    ):
        longitude, latitude = float(value[0]), float(value[1])
        if -180 <= longitude <= 180 and -90 <= latitude <= 90:
            yield longitude, latitude
        return
    for child in value:
        yield from _iter_coordinate_pairs(child)


def _geojson_bounds(payload):
    coordinates = []
    for feature in payload.get("features", []):
        geometry = feature.get("geometry") or {}
        coordinates.extend(_iter_coordinate_pairs(geometry.get("coordinates")))
    if not coordinates:
        return None
    longitudes, latitudes = zip(*coordinates)
    return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]


def _viewer_project_payload(name, map_view, layers, startup_dataset_id=None):
    return {
        "version": "0.1.0",
        "name": name,
        "mapView": map_view,
        "basemapStyleUrl": "https://tiles.openfreemap.org/styles/liberty",
        "basemapVisible": True,
        "basemapOpacity": 1,
        "layers": layers,
        "styles": {},
        "plugins": {
            "activePluginIds": [VIEWER_PLUGIN_ID],
            "mapControlPositions": {},
            "settings": {
                VIEWER_PLUGIN_ID: {
                    "autoShowAll": True,
                    "autoFocus": True,
                    "simplifiedViewer": True,
                    "startupDatasetId": startup_dataset_id,
                }
            },
        },
        "metadata": {
            "generatedBy": "OS-LocationDataVisualizer",
            "preliminary": True,
        },
    }


def create_empty_geolibre_project(project_path):
    """Create a clean viewer project ready for KML or GeoJSON drag and drop."""
    project_path = Path(project_path)
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project = _viewer_project_payload(
        "OS-LOC-DAT-VIZ Viewer",
        {
            "center": [0, 0],
            "zoom": 2,
            "bearing": 0,
            "pitch": 0,
        },
        [],
    )
    project_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    return project_path


def create_geolibre_project(geojson_path, project_path=None, display_name=None):
    """Create a GeoLibre project that restores the generated local GeoJSON layer."""
    geojson_path = Path(geojson_path).resolve()
    if not geojson_path.is_file():
        raise GeoLibreLaunchError(f"Generated GeoJSON file is missing: {geojson_path}")

    try:
        geojson_payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GeoLibreLaunchError(f"Generated GeoJSON could not be read: {error}") from error
    if geojson_payload.get("type") != "FeatureCollection":
        raise GeoLibreLaunchError("Generated GeoJSON is not a FeatureCollection")

    bounds = _geojson_bounds(geojson_payload)
    if bounds:
        center = [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2]
    else:
        center = [0, 0]

    layer_name = display_name or geojson_path.stem
    dataset_id = geojson_payload.get("osloc_dataset_id")
    map_view = {
        "center": center,
        "zoom": 12 if bounds else 2,
        "bearing": 0,
        "pitch": 0,
    }
    if bounds:
        map_view["bbox"] = bounds

    project = _viewer_project_payload(
        layer_name,
        map_view,
        [
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, geojson_path.as_uri())),
                "name": layer_name,
                "type": "geojson",
                "source": {"type": "geojson"},
                "sourcePath": str(geojson_path),
                "visible": True,
                "opacity": 1,
                "metadata": {
                    "generatedBy": "OS-LocationDataVisualizer",
                    "preliminary": True,
                    "localFileReloadable": True,
                },
            }
        ],
        dataset_id,
    )

    project_path = (
        Path(project_path) if project_path else geojson_path.with_suffix(".geolibre")
    )
    project_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    return project_path


def _is_geolibre_process_running():
    if sys.platform != "win32":
        return False

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [
                "tasklist",
                "/FI",
                f"IMAGENAME eq {GEOLIBRE_EXECUTABLE_NAME}",
                "/FO",
                "CSV",
                "/NH",
            ],
            capture_output=True,
            text=True,
            check=False,
            creationflags=creation_flags,
        )
    except OSError as error:
        raise GeoLibreLaunchError(f"Could not check for a running GeoLibre viewer: {error}") from error

    for row in csv.reader(result.stdout.splitlines()):
        if row and row[0].strip().lower() == GEOLIBRE_EXECUTABLE_NAME:
            return True
    return False


def launch_geolibre_viewer(
    geojson_path=None,
    project_path=None,
    display_name=None,
    runtime_root=None,
    resource_root=None,
):
    """Prepare the bundled viewer and launch a generated or empty project."""
    global _viewer_process

    managed_viewer_running = _viewer_process is not None and _viewer_process.poll() is None
    if not managed_viewer_running and _is_geolibre_process_running():
        raise GeoLibreLaunchError(
            "GeoLibre is already running. Close it, then open the included viewer again "
            "so the included viewer can load its required plugin and simplified interface."
        )

    runtime_root = Path(runtime_root) if runtime_root else default_runtime_root()
    executable_path = ensure_geolibre_installed(runtime_root, resource_root)
    provision_geolibre_integration(resource_root=resource_root)
    if geojson_path is None:
        project_path = project_path or runtime_root / "projects" / "open-viewer.geolibre"
        project_path = create_empty_geolibre_project(project_path)
    else:
        project_path = create_geolibre_project(geojson_path, project_path, display_name)

    try:
        process = subprocess.Popen(
            [str(executable_path), str(project_path.resolve())],
            cwd=str(executable_path.parent),
            env=os.environ.copy(),
            close_fds=True,
        )
    except OSError as error:
        raise GeoLibreLaunchError(f"Could not start bundled GeoLibre: {error}") from error
    if not managed_viewer_running:
        _viewer_process = process
    return project_path


class GeoLibreLaunchWorker(QThread):
    """Prepare and start GeoLibre without blocking the application UI."""

    launched = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, geojson_path=None, display_name=None, parent=None):
        super().__init__(parent)
        self.geojson_path = Path(geojson_path) if geojson_path is not None else None
        self.display_name = display_name

    def run(self):
        try:
            project_path = launch_geolibre_viewer(
                self.geojson_path,
                display_name=self.display_name,
            )
            self.launched.emit(str(project_path))
        except Exception as error:
            self.error.emit(str(error))