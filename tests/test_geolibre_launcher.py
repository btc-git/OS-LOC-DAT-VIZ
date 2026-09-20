"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import hashlib
import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

import geolibre_launcher
from geolibre_launcher import (
    GEOLIBRE_EXECUTABLE_NAME,
    GeoLibreLaunchError,
    VIEWER_PLUGIN_ID,
    _is_geolibre_process_running,
    _safe_extract_zip,
    create_empty_geolibre_project,
    create_geolibre_project,
    ensure_geolibre_installed,
    launch_geolibre_viewer,
    provision_geolibre_integration,
)
from license_dialog import LicenseDialog
from main_window import MainWindow
from import_wizard import SourceFileLoadWorker


class GeoLibreProjectTests(unittest.TestCase):
    def test_empty_project_activates_drop_ready_viewer(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_path = create_empty_geolibre_project(
                Path(temporary_directory) / "projects" / "open-viewer.geolibre"
            )
            project = json.loads(project_path.read_text(encoding="utf-8"))
            plugin_settings = project["plugins"]["settings"][VIEWER_PLUGIN_ID]

            self.assertEqual("OS-LOC-DAT-VIZ Viewer", project["name"])
            self.assertEqual([], project["layers"])
            self.assertEqual(
                [VIEWER_PLUGIN_ID], project["plugins"]["activePluginIds"]
            )
            self.assertTrue(plugin_settings["autoShowAll"])
            self.assertTrue(plugin_settings["autoFocus"])
            self.assertTrue(plugin_settings["simplifiedViewer"])
            self.assertIsNone(plugin_settings["startupDatasetId"])

    def test_project_references_generated_geojson_and_activates_viewer(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            geojson_path = root / "records.geojson"
            geojson_path.write_text(
                json.dumps({
                    "type": "FeatureCollection",
                    "osloc_dataset_id": "dataset-123",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[-77.7, 43.1], [-77.5, 43.3]],
                            },
                            "properties": {},
                        }
                    ],
                }),
                encoding="utf-8",
            )

            project_path = create_geolibre_project(
                geojson_path, display_name="Review Records"
            )
            project = json.loads(project_path.read_text(encoding="utf-8"))
            layer = project["layers"][0]
            plugin_settings = project["plugins"]["settings"][VIEWER_PLUGIN_ID]

            self.assertEqual("0.1.0", project["version"])
            self.assertEqual("Review Records", project["name"])
            self.assertEqual([-77.6, 43.2], project["mapView"]["center"])
            self.assertEqual([-77.7, 43.1, -77.5, 43.3], project["mapView"]["bbox"])
            self.assertEqual(str(geojson_path.resolve()), layer["sourcePath"])
            self.assertTrue(layer["metadata"]["localFileReloadable"])
            self.assertNotIn("geojson", layer)
            self.assertEqual([VIEWER_PLUGIN_ID], project["plugins"]["activePluginIds"])
            self.assertTrue(plugin_settings["autoShowAll"])
            self.assertTrue(plugin_settings["autoFocus"])
            self.assertTrue(plugin_settings["simplifiedViewer"])
            self.assertEqual("dataset-123", plugin_settings["startupDatasetId"])

    def test_project_rejects_non_feature_collection(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            geojson_path = Path(temporary_directory) / "invalid.geojson"
            geojson_path.write_text('{"type":"Feature"}', encoding="utf-8")

            with self.assertRaisesRegex(GeoLibreLaunchError, "FeatureCollection"):
                create_geolibre_project(geojson_path)


class GeoLibreProvisioningTests(unittest.TestCase):
    def _write_plugin(self, resource_root):
        plugin_root = resource_root / "GeoLibre-Plugin"
        (plugin_root / "dist").mkdir(parents=True)
        (resource_root / "LICENSE").write_text(
            "GPL test license", encoding="utf-8"
        )
        (plugin_root / "plugin.json").write_text(
            json.dumps({
                "id": VIEWER_PLUGIN_ID,
                "name": "OS-LOC-DAT-VIZ Viewer",
                "version": "test",
                "entry": "dist/index.js",
                "style": "dist/style.css",
            }),
            encoding="utf-8",
        )
        (plugin_root / "dist" / "index.js").write_text("export default {};", encoding="utf-8")
        (plugin_root / "dist" / "style.css").write_text(".viewer {}", encoding="utf-8")

    def test_integration_installs_current_plugin_without_admin_profile(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            resource_root = root / "resources"
            geolibre_data_root = root / "GeoLibreData"
            self._write_plugin(resource_root)

            plugin_path = provision_geolibre_integration(
                resource_root, geolibre_data_root
            )

            self.assertEqual(
                geolibre_data_root / "plugins" / f"{VIEWER_PLUGIN_ID}.zip",
                plugin_path,
            )
            self.assertFalse((geolibre_data_root / "admin-profile.json").exists())
            with zipfile.ZipFile(plugin_path) as archive:
                self.assertEqual(
                    {"plugin.json", "dist/index.js", "dist/style.css", "LICENSE"},
                    set(archive.namelist()),
                )
                self.assertEqual(
                    "GPL test license",
                    archive.read("LICENSE").decode("utf-8"),
                )

    def test_pinned_viewer_archive_is_extracted_once(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = (
                root
                / "resources"
                / "GeoLibre-Viewer"
                / geolibre_launcher.GEOLIBRE_ARCHIVE_NAME
            )
            archive_path.parent.mkdir(parents=True)
            (archive_path.parent / "LICENSE-GeoLibre.txt").write_text(
                "MIT test license", encoding="utf-8"
            )
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(f"portable/{GEOLIBRE_EXECUTABLE_NAME}", b"viewer")
                archive.writestr("portable/resources/readme.txt", b"resource")

            expected_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            runtime_root = root / "runtime"
            with patch.object(geolibre_launcher, "GEOLIBRE_ARCHIVE_SHA256", expected_hash):
                executable_path = ensure_geolibre_installed(
                    runtime_root, root / "resources"
                )
                archive_path.unlink()
                cached_path = ensure_geolibre_installed(
                    runtime_root, root / "resources"
                )

            self.assertEqual(b"viewer", executable_path.read_bytes())
            self.assertEqual(executable_path, cached_path)
            self.assertEqual(
                "MIT test license",
                (executable_path.parents[1] / "LICENSE-GeoLibre.txt").read_text(
                    encoding="utf-8"
                ),
            )

    def test_archive_extraction_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive_path = root / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escaped.txt", "no")

            with self.assertRaisesRegex(GeoLibreLaunchError, "unsafe path"):
                _safe_extract_zip(archive_path, root / "destination")
            self.assertFalse((root / "escaped.txt").exists())


class GeoLibreProcessTests(unittest.TestCase):
    @patch.object(geolibre_launcher, "_viewer_process", None)
    @patch.object(geolibre_launcher, "_is_geolibre_process_running", return_value=False)
    @patch.object(geolibre_launcher, "provision_geolibre_integration")
    @patch.object(geolibre_launcher, "ensure_geolibre_installed")
    @patch.object(geolibre_launcher.subprocess, "Popen")
    def test_launch_without_geojson_opens_empty_project(
        self, popen_mock, install_mock, _provision_mock, _running_mock
    ):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            executable_path = root / "portable" / GEOLIBRE_EXECUTABLE_NAME
            executable_path.parent.mkdir(parents=True)
            executable_path.write_bytes(b"viewer")
            install_mock.return_value = executable_path

            project_path = launch_geolibre_viewer(
                runtime_root=root / "runtime",
                resource_root=root / "resources",
            )

            project = json.loads(project_path.read_text(encoding="utf-8"))
            self.assertEqual([], project["layers"])
            self.assertEqual(
                [str(executable_path), str(project_path.resolve())],
                popen_mock.call_args.args[0],
            )

    @patch.object(geolibre_launcher.sys, "platform", "win32")
    @patch.object(geolibre_launcher.subprocess, "run")
    def test_running_process_detection_uses_exact_image_name(self, run_mock):
        run_mock.return_value = Mock(
            stdout='"geolibre-desktop.exe","1234","Console","1","10,000 K"\n'
        )
        self.assertTrue(_is_geolibre_process_running())

        run_mock.return_value = Mock(stdout='INFO: No tasks are running which match the specified criteria.\n')
        self.assertFalse(_is_geolibre_process_running())

    @patch.object(geolibre_launcher, "_viewer_process", None)
    @patch.object(geolibre_launcher, "_is_geolibre_process_running", return_value=True)
    @patch.object(geolibre_launcher, "ensure_geolibre_installed")
    def test_launch_refuses_handoff_to_unmanaged_geolibre(
        self, install_mock, _running_mock
    ):
        with self.assertRaisesRegex(GeoLibreLaunchError, "already running"):
            launch_geolibre_viewer("unused.geojson")
        install_mock.assert_not_called()


class GenerationActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_exposes_save_and_viewer_actions(self):
        with patch.object(MainWindow, "show_disclaimer_dialog"):
            window = MainWindow()
        self.addCleanup(window.close)

        self.assertEqual("Save Outputs", window.generate_button.text())
        self.assertEqual("Save & Open Viewer", window.viewer_button.text())
        self.assertEqual("Open Viewer", window.open_viewer_button.text())
        self.assertEqual(
            ["YMD", "YDM", "MDY", "DMY"],
            [
                window.source_date_order_combo.itemData(index)
                for index in range(window.source_date_order_combo.count())
            ],
        )
        self.assertFalse(window.generate_button.isEnabled())
        self.assertFalse(window.viewer_button.isEnabled())
        self.assertTrue(window.open_viewer_button.isEnabled())

        window.set_generation_actions_enabled(True)
        with (
            patch.object(window, "generate_kml") as generate_mock,
            patch.object(window, "start_geolibre_viewer") as open_mock,
        ):
            window.generate_button.click()
            window.viewer_button.click()
            window.open_viewer_button.click()

        self.assertEqual(
            [call(open_viewer=False), call(open_viewer=True)],
            generate_mock.call_args_list,
        )
        open_mock.assert_called_once_with()

    def test_license_dialog_includes_bundled_geolibre_notice(self):
        dialog = LicenseDialog()
        self.addCleanup(dialog.close)

        license_text = dialog.license_label.text()
        self.assertEqual(
            "Licenses & Third-Party Notices", dialog.windowTitle()
        )
        self.assertIn("OS-LOC-DAT-VIZ - GNU GPL v3.0", license_text)
        self.assertIn("BUNDLED THIRD-PARTY SOFTWARE", license_text)
        self.assertIn("GeoLibre 3.0.0", license_text)
        self.assertIn("Copyright (c) 2026 Qiusheng Wu", license_text)
        self.assertIn("MIT License", license_text)

    def test_import_timestamp_settings_are_mirrored_in_main_controls(self):
        with patch.object(MainWindow, "show_disclaimer_dialog"):
            window = MainWindow()
        self.addCleanup(window.close)

        window.apply_import_timestamp_settings(SimpleNamespace(
            selected_source_timezone_name="UTC",
            selected_source_offset_minutes=0,
            selected_target_timezone_name="America/New_York",
            selected_target_offset_minutes=0,
            selected_date_order="YMD",
        ))

        self.assertEqual("UTC", window.source_timezone_combo.currentData())
        self.assertEqual(
            "UTC (UTC+00:00)", window.source_timezone_combo.currentText()
        )
        self.assertTrue(window.source_utc_offset_combo.isHidden())
        self.assertEqual(
            ("America/New_York", 0),
            (
                window.import_target_timezone_name,
                window.import_target_offset_minutes,
            ),
        )
        self.assertIn("US Eastern", window.target_timezone_combo.currentText())
        self.assertEqual("YMD", window.source_date_order_combo.currentData())

        window.apply_import_timestamp_settings(SimpleNamespace(
            selected_source_timezone_name=None,
            selected_source_offset_minutes=-300,
            selected_target_timezone_name=None,
            selected_target_offset_minutes=None,
            selected_date_order="DMY",
        ))

        self.assertIsNone(window.source_timezone_combo.currentData())
        self.assertEqual(-300, window.source_utc_offset_combo.currentData())
        self.assertFalse(window.source_utc_offset_combo.isHidden())
        self.assertEqual("No Change", window.target_timezone_combo.currentText())
        self.assertEqual(
            (None, None),
            (
                window.import_target_timezone_name,
                window.import_target_offset_minutes,
            ),
        )

    def test_file_drop_inspects_headers_with_busy_progress(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "records.csv"
            source_path.write_text(
                "Timestamp,Latitude,Longitude\n"
                "2024-01-15 14:00:00,43.15,-77.61\n",
                encoding="utf-8",
            )
            with patch.object(MainWindow, "show_disclaimer_dialog"):
                window = MainWindow()
            self.addCleanup(window.close)
            inspection_finished = QSignalSpy(
                window.file_inspection_finished
            )
            reader_started = threading.Event()
            release_reader = threading.Event()
            original_read_source = SourceFileLoadWorker.read_source

            def delayed_read_source(*args, **kwargs):
                reader_started.set()
                release_reader.wait(5)
                return original_read_source(*args, **kwargs)

            with patch.object(
                SourceFileLoadWorker,
                "read_source",
                side_effect=delayed_read_source,
            ):
                window.handle_file_selection(str(source_path))
                while not reader_started.is_set():
                    self.app.processEvents()

                heartbeat = []
                QTimer.singleShot(0, lambda: heartbeat.append(True))
                self.app.processEvents()

                self.assertEqual([True], heartbeat)
                self.assertFalse(window.progress_bar.isHidden())
                self.assertFalse(window.drag_drop_widget.isEnabled())
                release_reader.set()
                self.assertTrue(inspection_finished.wait(5000))
            self.app.processEvents()
            self.assertTrue(inspection_finished[0][0])
            self.assertTrue(window.progress_bar.isHidden())
            self.assertTrue(window.drag_drop_widget.isEnabled())
            self.assertTrue(window.generate_button.isEnabled())

    def test_custom_headers_open_mapping_after_background_inspection(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "custom.csv"
            source_path.write_text(
                "Start_DateTime,Tower_Lat,Tower_Lon\n"
                "2024-01-15 14:00:00,43.15,-77.61\n",
                encoding="utf-8",
            )
            with patch.object(MainWindow, "show_disclaimer_dialog"):
                window = MainWindow()
            self.addCleanup(window.close)
            inspection_finished = QSignalSpy(
                window.file_inspection_finished
            )

            with patch.object(
                window, "show_import_wizard", return_value=False
            ) as wizard:
                window.handle_file_selection(str(source_path))
                self.assertTrue(inspection_finished.wait(5000))

            wizard.assert_called_once_with(str(source_path))
            self.assertTrue(window.progress_bar.isHidden())

    def test_viewer_action_saves_all_outputs_before_launch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "source.csv"
            source_path.write_text("Timestamp,Latitude,Longitude\n", encoding="utf-8")
            output_path = root / "result.kml"

            with patch.object(MainWindow, "show_disclaimer_dialog"):
                window = MainWindow()
            self.addCleanup(window.close)
            window.current_generation_source_file = str(source_path)
            window.current_generation_settings = {}
            window.open_viewer_after_generation = True

            with (
                patch(
                    "main_window.QFileDialog.getSaveFileName",
                    return_value=(str(output_path), "KML Files (*.kml)"),
                ),
                patch.object(window, "build_generation_log", return_value="log\n"),
                patch.object(window, "start_geolibre_viewer") as launch_mock,
            ):
                window.on_generation_finished({
                    "kml": "<kml/>",
                    "geojson": '{"type":"FeatureCollection","features":[]}',
                })

            self.assertEqual("<kml/>", output_path.read_text(encoding="utf-8"))
            self.assertTrue(output_path.with_suffix(".geojson").is_file())
            self.assertEqual("log\n", output_path.with_suffix(".txt").read_text(encoding="utf-8"))
            launch_mock.assert_called_once_with(output_path.with_suffix(".geojson"))


if __name__ == "__main__":
    unittest.main()