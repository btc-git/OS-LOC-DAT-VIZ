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

import pandas as pd
from openpyxl import load_workbook

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import (
    QApplication, QAbstractButton, QFileDialog, QHBoxLayout, QLabel, QScrollArea, QToolButton,
)

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
from dialogs import DisclaimerDialog
from main_window import MainWindow
from import_wizard import ImportWizardDialog, SourceFileLoadWorker


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
            self.assertFalse(plugin_settings["autoShowAll"])
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
            self.assertFalse(plugin_settings["autoShowAll"])
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
    def test_generated_viewer_creates_companion_project(
        self, popen_mock, install_mock, _provision_mock, _running_mock
    ):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            executable_path = root / "portable" / GEOLIBRE_EXECUTABLE_NAME
            executable_path.parent.mkdir(parents=True)
            executable_path.write_bytes(b"viewer")
            install_mock.return_value = executable_path
            output_root = root / "outputs"
            output_root.mkdir()
            geojson_path = output_root / "records.geojson"
            geojson_path.write_text(
                json.dumps({"type": "FeatureCollection", "features": []}),
                encoding="utf-8",
            )

            project_path = launch_geolibre_viewer(
                geojson_path, runtime_root=root / "runtime"
            )

            expected_project_path = geojson_path.resolve().with_suffix(".geolibre")
            self.assertEqual(expected_project_path, project_path)
            self.assertEqual(
                str(geojson_path.resolve()),
                json.loads(project_path.read_text(encoding="utf-8"))["layers"][0][
                    "sourcePath"
                ],
            )
            self.assertEqual(
                [str(executable_path), str(project_path.resolve())],
                popen_mock.call_args.args[0],
            )

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
    def test_marker_dataframe_accepts_named_and_hex_colors(self):
        markers, warnings = MainWindow.parse_marker_dataframe(pd.DataFrame([
            {
                "Marker Label": "Residence",
                "Lat": "43.158310",
                "Lon": "-77.609380",
                "Marker Color": "orange",
            },
            {
                "Marker Label": "Meeting point",
                "Lat": 43.2,
                "Lon": -77.7,
                "Marker Color": "#3366CC",
            },
        ]))

        self.assertEqual([], warnings)
        self.assertEqual(2, len(markers))
        self.assertEqual("Residence", markers[0]["label"])
        self.assertEqual("43.158310", markers[0]["latitude_text"])
        self.assertEqual("#ffa500", markers[0]["color"])
        self.assertEqual("#3366cc", markers[1]["color"])
        self.assertEqual([2, 3], [marker["source_row"] for marker in markers])

    def test_marker_dataframe_skips_invalid_rows_with_warnings(self):
        markers, warnings = MainWindow.parse_marker_dataframe(pd.DataFrame([
            {"Label": "Valid", "Latitude": 43.1, "Longitude": -77.1,
             "Color": "green"},
            {"Label": "", "Latitude": 43.2, "Longitude": -77.2,
             "Color": "blue"},
            {"Label": "Bad coordinate", "Latitude": 95,
             "Longitude": -77.3, "Color": "purple"},
            {"Label": "Bad color", "Latitude": 43.4,
             "Longitude": -77.4, "Color": "chartreuse-ish"},
            {"Label": None, "Latitude": None, "Longitude": None,
             "Color": None},
        ], dtype=object), header_row=3)

        self.assertEqual(["Valid"], [marker["label"] for marker in markers])
        self.assertEqual(3, len(warnings))
        self.assertIn("Row 5: label is blank", warnings)
        self.assertIn("Row 6: latitude must be between -90 and 90", warnings)
        self.assertTrue(any(
            warning.startswith("Row 7: color must be a name")
            for warning in warnings
        ))

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_exposes_process_and_viewer_actions(self):
        with patch.object(MainWindow, "show_disclaimer_dialog"):
            window = MainWindow()
        self.addCleanup(window.close)

        self.assertEqual("Process", window.generate_button.text())
        self.assertEqual("Process and Open in Viewer", window.viewer_button.text())
        self.assertEqual("Open Viewer", window.open_viewer_button.text())
        self.assertEqual("Cell Site/Sector Data", window.tower_radio.text())
        self.assertEqual("Distance from Cell Site Data", window.ta_radio.text())
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

    def test_site_template_download_names_preserve_internal_keys(self):
        window = MainWindow()
        self.addCleanup(window.close)
        cases = (
            ("cell_tower", "Cell Site/Sector Data Template", "cell_site_sector_template.xlsx"),
            (
                "distance_from_tower", "Distance from Cell Site Data Template",
                "distance_from_cell_site_template.xlsx",
            ),
        )
        for key, description, filename in cases:
            with self.subTest(template=key), patch(
                "main_window.QFileDialog.getSaveFileName",
                return_value=("", ""),
            ) as save_dialog:
                window.download_template(key)
                self.assertEqual(
                    (window, f"Save {description}", filename,
                     "Excel Files (*.xlsx);;All Files (*)"),
                    save_dialog.call_args.args,
                )

    def test_application_and_disclaimer_visible_text_uses_sites(self):
        window = MainWindow()
        self.addCleanup(window.close)
        dialog = DisclaimerDialog(window)
        self.addCleanup(dialog.close)
        for container in (window, dialog):
            for widget_type in (QLabel, QAbstractButton):
                for widget in container.findChildren(widget_type):
                    self.assertNotIn("tower", widget.text().lower())
                    self.assertNotIn("tower", widget.toolTip().lower())

    def test_settings_retain_tooltips_without_extra_help_controls(self):
        window = MainWindow()
        self.addCleanup(window.close)
        settings_tab = window.tab_widget.widget(1)
        self.assertIsInstance(settings_tab, QScrollArea)
        settings_widget = settings_tab.widget()
        self.assertEqual([], settings_widget.findChildren(QToolButton))
        labels = [
            label for label in settings_widget.findChildren(QLabel)
            if label.toolTip()
        ]
        self.assertEqual(14, len(labels))
        grid = settings_widget.layout()
        self.assertEqual(
            "Hover over labels for more information.",
            grid.itemAtPosition(0, 0).widget().text(),
        )
        for label in labels:
            item = next(
                grid.itemAt(index)
                for index in range(grid.count())
                if grid.itemAt(index).widget() is label
            )
            self.assertIs(label, item.widget())
            self.assertFalse(label.wordWrap())
        radius_help = next(
            label for label in labels
            if "Nearby Cell Site Radius" in label.text()
        )
        self.assertIn("Only applies when using a separate cell site list", radius_help.toolTip())
        self.assertIn("this radius has no effect", radius_help.toolTip())
        self.assertIn("does not estimate coverage", radius_help.toolTip())
        self.assertEqual(25.0, window.reference_site_radius_spinbox.value())
        self.assertEqual(0, window.default_accuracy_spinbox.minimum())
        self.assertEqual(0, window.default_accuracy_spinbox.value())
        accuracy_help = next(
            label for label in labels if label.text() == "Default Location Accuracy:"
        )
        self.assertIn("accuracy is unknown, not exact", accuracy_help.toolTip())

    def test_color_tooltips_preserve_original_controls(self):
        window = MainWindow()
        self.addCleanup(window.close)
        colors_tab = window.tab_widget.widget(2)
        self.assertEqual([], colors_tab.findChildren(QToolButton))
        grid = colors_tab.layout()
        self.assertEqual(
            "Hover over labels for more information.",
            grid.itemAtPosition(0, 0).widget().text(),
        )
        color_buttons = (
            window.leg_color_button, window.shaded_color_button,
            window.band_color_button, window.gps_color_button,
            window.reference_site_color_button,
        )
        for row, color_button in enumerate(color_buttons, 1):
            self.assertIs(color_button, grid.itemAtPosition(row, 1).widget())
            label = grid.itemAtPosition(row, 0).widget()
            self.assertIsInstance(label, QLabel)
            self.assertFalse(label.wordWrap())
            self.assertTrue(label.toolTip())
        with patch.object(window, "select_color") as select_color:
            for button in color_buttons:
                button.click()
        self.assertEqual(
            [call("leg"), call("shaded"), call("band"), call("gps"),
             call("reference_site")],
            select_color.call_args_list,
        )

    def test_disclaimer_describes_current_workflows_and_troubleshooting(self):
        dialog = DisclaimerDialog()
        self.addCleanup(dialog.close)
        text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
        for phrase in (
            "Preliminary Visualization Only",
            "KML and GeoJSON visualizations",
            "Process and Open in Viewer",
            "Open Viewer",
            "Load GeoJSON",
            ".geolibre",
            "Check Matching Rows",
            "Use exact times",
            "separate cell site list",
            "Reference Cell Sites",
            "initially 0",
            "A zero default means no accuracy radius is assumed",
            "A source accuracy value of zero also means unknown accuracy",
            "Azimuth is measured in degrees",
            "Invalid accuracy produces a point",
            "Other date and time options:",
            "Excel stores as numbers",
            "such as -05:00",
            "a Date column and a Time column",
            "March 4 or April 3",
            "14:30:00.123 is treated as 14:30:00",
            "A time without a date uses today's date",
            "Missing or unreadable dates and times:",
            "For all record types",
            "date/time unavailable",
            "cannot confirm that they fall within your selected range",
            "GeoJSON output in the included GeoLibre viewer",
            "No RF Coverage Estimates",
            "additional points of interest",
            "map area being requested",
            "Invalid accuracy produces a point without an accuracy circle, even when a positive default is configured",
            "performance still depends",
            "Show All",
            "From/Through",
            "Focus Set",
            "one running instance per Windows session",
            "map services",
            "OpenFreeMap",
            "IP address and the map area being requested",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        self.assertNotIn("milliseconds auto-handled", text)
        self.assertNotIn("additonal", text)
        self.assertNotIn("RF coverages", text)
        self.assertNotIn("18+ timestamp formats", text)

    def test_main_timezone_defaults_match_import_wizard(self):
        with patch.object(MainWindow, "show_disclaimer_dialog"):
            window = MainWindow()
        self.addCleanup(window.close)

        self.assertEqual(
            "Fixed UTC+00:00", window.source_timezone_combo.currentText()
        )
        self.assertEqual("No Change", window.target_timezone_combo.currentText())
        self.assertEqual(
            [
                window.source_timezone_combo.itemText(index)
                for index in range(window.source_timezone_combo.count())
            ],
            [
                window.target_timezone_combo.itemText(index)
                for index in range(1, window.target_timezone_combo.count())
            ],
        )

    @patch("main_window.KMLGenerator")
    def test_generation_passes_reference_sites_and_settings(self, generator_class):
        with patch.object(MainWindow, "show_disclaimer_dialog"):
            window = MainWindow()
        self.addCleanup(window.close)
        reference_sites = object()
        window.data_file = "records.csv"
        window.reference_sites_dataframe = reference_sites
        window.tower_radio.setChecked(True)
        window.reference_site_radius_spinbox.setValue(15.0)
        window.reference_site_color = "ff332211"
        window.add_marker_row({
            "label": "Office",
            "latitude_text": "43.123400",
            "longitude_text": "-77.567800",
            "color": "orange",
        })

        window.generate_kml()

        arguments = generator_class.call_args
        settings = arguments.args[2]
        self.assertTrue(settings["include_reference_sites"])
        self.assertEqual(15.0, settings["reference_site_radius_miles"])
        self.assertEqual("ff332211", settings["reference_site_color"])
        self.assertIs(reference_sites, arguments.kwargs["reference_sites"])
        self.assertEqual("Office", arguments.kwargs["markers"][0]["label"])
        self.assertEqual(
            "#ffa500", arguments.kwargs["markers"][0]["color"]
        )
        generator_class.return_value.start.assert_called_once_with()

    def test_license_dialog_includes_bundled_geolibre_notice(self):
        dialog = LicenseDialog()
        self.addCleanup(dialog.close)

        license_text = dialog.license_label.text()
        self.assertEqual(
            "Licenses & Third-Party Notices", dialog.windowTitle()
        )
        self.assertIn("OS-LOC-DAT-VIZ - GNU GPL v3.0", license_text)
        self.assertIn("THIRD-PARTY DEPENDENCY INVENTORY", license_text)
        self.assertIn("PyQt6", license_text)
        self.assertIn("pandas", license_text)
        self.assertIn("BUNDLED THIRD-PARTY SOFTWARE", license_text)
        self.assertIn("GeoLibre 3.0.0", license_text)
        self.assertIn("Copyright (c) 2026 Qiusheng Wu", license_text)
        self.assertIn("MIT License", license_text)

    def test_import_timestamp_settings_are_mirrored_in_main_controls(self):
        with patch.object(MainWindow, "show_disclaimer_dialog"):
            window = MainWindow()
        self.addCleanup(window.close)

        window.apply_import_timestamp_settings(SimpleNamespace(
            selected_source_timezone_name=None,
            selected_source_offset_minutes=0,
            selected_target_timezone_name="America/New_York",
            selected_target_offset_minutes=0,
            selected_date_order="YMD",
        ))

        self.assertEqual(
            (None, 0),
            ImportWizardDialog.timezone_selection(window.source_timezone_combo),
        )
        self.assertEqual(
            "Fixed UTC+00:00", window.source_timezone_combo.currentText()
        )
        self.assertEqual(
            ("America/New_York", 0),
            (
                window.import_target_timezone_name,
                window.import_target_offset_minutes,
            ),
        )
        self.assertIn("US Eastern", window.target_timezone_combo.currentText())
        self.assertEqual("YMD", window.source_date_order_combo.currentData())

    def test_markers_tab_collects_manual_rows_and_colors(self):
        self.enterContext(patch.object(MainWindow, "show_disclaimer_dialog"))
        window = MainWindow()
        self.addCleanup(window.close)

        self.assertEqual(
            ["Data Type", "Settings", "Colors", "Markers"],
            [
                window.tab_widget.tabText(index)
                for index in range(window.tab_widget.count())
            ],
        )
        self.assertTrue(window.marker_drop_widget.property("compact"))
        self.assertIsInstance(window.marker_drop_widget.layout(), QHBoxLayout)
        self.assertLessEqual(window.marker_drop_widget.maximumHeight(), 62)
        self.assertEqual("— OR —", window.marker_drop_widget.or_label.text())
        self.assertEqual(
            "Import a list above or add markers individually below.",
            window.marker_entry_hint.text(),
        )

        window.resize(768, 1057)
        window.show()
        self.app.processEvents()
        table_width = window.marker_table.viewport().width()
        self.assertLessEqual(window.marker_table.columnWidth(0), table_width * 0.43)
        self.assertLessEqual(
            abs(
                window.marker_table.columnWidth(1)
                - window.marker_table.columnWidth(2)
            ),
            1,
        )
        for column, header_text in ((1, "Latitude"), (2, "Longitude")):
            required_width = (
                window.marker_table.fontMetrics().horizontalAdvance(header_text)
                + 24
            )
            self.assertGreaterEqual(
                window.marker_table.columnWidth(column), required_width
            )
        self.assertEqual(92, window.marker_table.columnWidth(3))
        self.assertEqual(40, window.marker_table.columnWidth(4))

        window.add_marker_row()
        window.marker_table.item(0, 0).setText("Court")
        window.marker_table.item(0, 1).setText("43.158310")
        window.marker_table.item(0, 2).setText("-77.609380")
        window.set_marker_button_color(
            window.marker_table.cellWidget(0, 3), "blue"
        )

        markers, warnings = window.marker_records_from_table()

        self.assertEqual([], warnings)
        self.assertEqual(1, len(markers))
        self.assertEqual("Court", markers[0]["label"])
        self.assertEqual("43.158310", markers[0]["latitude_text"])
        self.assertEqual("#0000ff", markers[0]["color"])
        self.assertEqual("1 marker", window.marker_count_label.text())

    def test_marker_file_import_appends_valid_rows(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker_path = Path(temporary_directory) / "markers.csv"
            marker_path.write_text(
                "Label,Latitude,Longitude,Color\n"
                "Office,43.10,-77.10,red\n"
                "Invalid,100,-77.20,green\n",
                encoding="utf-8",
            )
            with patch.object(MainWindow, "show_disclaimer_dialog"):
                window = MainWindow()
            self.addCleanup(window.close)

            window.add_marker_row({
                "label": "Existing",
                "latitude_text": "43.0",
                "longitude_text": "-77.0",
                "color": "black",
            })
            window.import_marker_file(str(marker_path))

            self.assertEqual(2, window.marker_table.rowCount())
            self.assertEqual("Office", window.marker_table.item(1, 0).text())
            self.assertEqual([str(marker_path)], window.marker_import_files)
            self.assertIn("Marker list Row 3", window.status_text.toPlainText())

    def test_compact_marker_drop_emits_spreadsheet_path(self):
        with patch.object(MainWindow, "show_disclaimer_dialog"):
            window = MainWindow()
        self.addCleanup(window.close)
        dropped_paths = []
        window.marker_drop_widget.file_dropped.disconnect()
        window.marker_drop_widget.file_dropped.connect(dropped_paths.append)
        url = Mock()
        url.isLocalFile.return_value = True
        url.toLocalFile.return_value = "markers.xlsx"
        event = Mock()
        event.mimeData.return_value.hasUrls.return_value = True
        event.mimeData.return_value.urls.return_value = [url]

        window.marker_drop_widget.dropEvent(event)

        self.assertEqual(["markers.xlsx"], dropped_paths)
        event.acceptProposedAction.assert_called_once_with()

    def test_markers_template_has_coordinate_and_color_columns(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            template_path = Path(temporary_directory) / "markers.xlsx"
            with patch.object(MainWindow, "show_disclaimer_dialog"):
                window = MainWindow()
            self.addCleanup(window.close)

            with (
                patch("main_window.QFileDialog.getSaveFileName", return_value=(
                    str(template_path), "Excel Files (*.xlsx)"
                )),
                patch.object(window, "open_file_location"),
                patch("main_window.QMessageBox.information"),
            ):
                window.download_template("markers")

            workbook = load_workbook(template_path, read_only=True)
            worksheet = workbook.active
            self.assertEqual(
                ["Label", "Latitude", "Longitude", "Color"],
                [cell.value for cell in worksheet[1]],
            )
            self.assertEqual("red", worksheet[2][3].value)
            workbook.close()

    def test_selecting_source_clears_markers_even_for_same_path(self):
        with patch.object(MainWindow, "show_disclaimer_dialog"):
            window = MainWindow()
        self.addCleanup(window.close)
        window.data_file = "records.csv"
        window.add_marker_row({
            "label": "Temporary",
            "latitude_text": "43.0",
            "longitude_text": "-77.0",
            "color": "black",
        })

        with patch.object(window, "start_file_inspection"):
            window.handle_file_selection("records.csv")

        self.assertEqual(0, window.marker_table.rowCount())
        self.assertEqual([], window.marker_import_files)

        window.apply_import_timestamp_settings(SimpleNamespace(
            selected_source_timezone_name=None,
            selected_source_offset_minutes=-300,
            selected_target_timezone_name=None,
            selected_target_offset_minutes=None,
            selected_date_order="DMY",
        ))

        self.assertEqual("Fixed UTC-05:00", window.source_timezone_combo.currentText())
        self.assertEqual(
            (None, -300),
            ImportWizardDialog.timezone_selection(window.source_timezone_combo),
        )
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
            selected_path = root / "result.geojson"
            kml_path = selected_path.with_suffix(".kml")

            with patch.object(MainWindow, "show_disclaimer_dialog"):
                window = MainWindow()
            self.addCleanup(window.close)
            window.current_generation_source_file = str(source_path)
            window.current_generation_settings = {}
            window.open_viewer_after_generation = True
            window.custom_label_input.setText("T-Mobile Location Estimates")

            with (
                patch(
                    "main_window.QFileDialog.getSaveFileName",
                    return_value=(str(selected_path), "GeoJSON Files (*.geojson)"),
                ) as save_dialog,
                patch.object(window, "build_generation_log", return_value="log\n"),
                patch.object(window, "start_geolibre_viewer") as launch_mock,
            ):
                window.on_generation_finished({
                    "kml": "<kml/>",
                    "geojson": '{"type":"FeatureCollection","features":[]}',
                })

            save_dialog.assert_called_once_with(
                window,
                "Save Processed Data Files",
                str(root / "T-Mobile_Location_Estimates.geojson"),
                "GeoJSON Files (*.geojson)",
                options=QFileDialog.Option.DontConfirmOverwrite,
            )
            self.assertEqual("<kml/>", kml_path.read_text(encoding="utf-8"))
            self.assertTrue(selected_path.is_file())
            self.assertEqual("log\n", selected_path.with_suffix(".txt").read_text(encoding="utf-8"))
            launch_mock.assert_called_once_with(selected_path)

    def test_generation_log_records_source_and_display_timezones(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "records.csv"
            output_path = root / "result.kml"
            source_path.write_text("records\n", encoding="utf-8")
            output_path.write_text("<kml/>\n", encoding="utf-8")
            output_path.with_suffix(".geojson").write_text(
                '{"type":"FeatureCollection","features":[]}\n',
                encoding="utf-8",
            )

            with patch.object(MainWindow, "show_disclaimer_dialog"):
                window = MainWindow()
            self.addCleanup(window.close)
            window.current_generation_source_file = str(source_path)
            window.current_generation_settings = {
                "source_timezone_name": None,
                "source_utc_offset_minutes": 0,
                "target_timezone_name": "America/New_York",
                "target_utc_offset_minutes": 0,
                "source_date_order": "MDY",
                "duration_minutes": 30,
            }
            window.current_generation_source_sha256 = window.calculate_file_sha256(source_path)
            window.current_generation_type = "Location Point"
            window.current_import_metadata = {
                "worksheet": None,
                "header_row": 1,
                "mappings": {"Timestamp": "Timestamp"},
                "cell_site_list": {"enabled": False},
                "date_time_filter": {
                    "enabled": True,
                    "exact_times": False,
                    "filter_timezone_label": "US Eastern (UTC-05:00 / UTC-04:00 DST)",
                    "filter_timezone_basis": "display",
                    "start_local": "2024-01-15 00:00:00",
                    "end_local": "2024-01-15 23:59:59",
                    "start_utc": "2024-01-15T05:00:00Z",
                    "end_utc": "2024-01-16T04:59:59Z",
                    "input_rows": 2,
                    "retained_rows": 1,
                    "excluded_rows": 1,
                    "unparseable_rows": 0,
                    "valid_coordinate_rows": 1,
                    "invalid_coordinate_rows": 0,
                },
            }

            log_text = window.build_generation_log(output_path)

            self.assertIn("Source timezone: Fixed UTC+00:00", log_text)
            self.assertIn(
                "Display timezone: US Eastern (UTC-05:00 / UTC-04:00 DST) "
                "[America/New_York]",
                log_text,
            )
            self.assertIn(
                "Filter timezone: US Eastern (UTC-05:00 / UTC-04:00 DST) "
                "(selected display timezone)",
                log_text,
            )
            self.assertIn(
                "Local range (inclusive): 2024-01-15 00:00:00 through "
                "2024-01-15 23:59:59",
                log_text,
            )
            self.assertIn(
                "UTC range (inclusive): 2024-01-15T05:00:00Z through "
                "2024-01-16T04:59:59Z",
                log_text,
            )

    def test_generation_log_records_cell_site_list_provenance(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_path = root / "records.csv"
            cell_site_path = root / "cell_sites.csv"
            marker_path = root / "markers.csv"
            output_path = root / "result.kml"
            source_path.write_text("records\n", encoding="utf-8")
            cell_site_path.write_text("cell sites\n", encoding="utf-8")
            marker_path.write_text("markers\n", encoding="utf-8")
            output_path.write_text("<kml/>\n", encoding="utf-8")
            output_path.with_suffix(".geojson").write_text(
                '{"type":"FeatureCollection","features":[]}\n',
                encoding="utf-8",
            )

            with patch.object(MainWindow, "show_disclaimer_dialog"):
                window = MainWindow()
            self.addCleanup(window.close)
            window.current_generation_source_file = str(source_path)
            window.current_generation_settings = {
                "include_reference_sites": True,
                "reference_site_radius_miles": 25.0,
                "reference_site_color": "ff000000",
            }
            window.current_generation_source_sha256 = window.calculate_file_sha256(source_path)
            window.current_generation_type = "Distance from Tower"
            window.current_generation_marker_count = 3
            window.current_marker_import_files = [str(marker_path)]
            window.current_marker_import_sources = [{
                "file_path": str(marker_path),
                "source_sha256": window.calculate_file_sha256(marker_path),
            }]
            window.current_import_metadata = {
                "worksheet": None,
                "header_row": 1,
                "mappings": {"Timestamp": "Start_DateTime"},
                "date_time_filter": {"enabled": False},
                "cell_site_list": {
                    "enabled": True,
                    "file_path": str(cell_site_path),
                    "source_sha256": window.calculate_file_sha256(cell_site_path),
                    "file_name": cell_site_path.name,
                    "worksheet": None,
                    "header_row": 1,
                    "policy": "cell_site_only",
                    "policy_label": "Cell site list only; unmatched values remain blank",
                    "original_key_mappings": {
                        "Site ID": "Start_eNodeB",
                        "Sector ID": "Start_Sector",
                    },
                    "cell_site_mappings": {
                        "Site ID": "E/G NodeB ID",
                        "Sector ID": "Cell ID",
                        "Latitude": "Site Lat",
                        "Longitude": "Site Long",
                        "Azimuth": "Azimuth",
                    },
                    "input_rows": 1,
                    "cell_site_rows": 1,
                    "cell_site_rows_ignored_missing_key": 0,
                    "duplicate_keys_collapsed": 2,
                    "duplicate_rows_collapsed": 3,
                    "unreferenced_conflicting_keys_ignored": 1,
                    "matched_rows": 1,
                    "unmatched_rows": 0,
                    "unmatched_source_rows": [],
                    "missing_key_rows": 0,
                    "missing_key_source_rows": [],
                    "fields_from_cell_site_list": {
                        "Latitude": 1,
                        "Longitude": 1,
                        "Azimuth": 1,
                    },
                    "fields_from_original_records": {
                        "Latitude": 0,
                        "Longitude": 0,
                        "Azimuth": 0,
                    },
                    "fields_left_missing": {
                        "Latitude": 0,
                        "Longitude": 0,
                        "Azimuth": 0,
                    },
                },
            }
            window.kml_generator = SimpleNamespace(audit_summary={
                "reference_site_source": "cell site list",
                "reference_sites_considered": 12,
                "reference_sites_generated": 5,
                "markers_generated": 3,
                "generated_without_timeline": 4,
                "generated_with_dst_conflict": 2,
                "skipped_missing_timestamp": 0,
                "skipped_dst_conflict": 0,
            })

            log_text = window.build_generation_log(output_path)
            expected_cell_site_hash = window.calculate_file_sha256(
                cell_site_path
            )

            self.assertIn("Cell site list file: cell_sites.csv", log_text)
            self.assertIn("Generated without timeline metadata: 4", log_text)
            self.assertIn(
                "Generated without timeline metadata - DST conflict: 2",
                log_text,
            )
            self.assertIn("Skipped - missing timestamp: 0", log_text)
            self.assertIn("Skipped - DST conflict: 0", log_text)
            self.assertIn("Record type: Distance from Cell Site", log_text)
            self.assertNotIn("tower", log_text.lower())
            self.assertIn(
                "Cell site field source: Cell site list only; unmatched values remain blank",
                log_text,
            )
            self.assertIn(
                f"Cell site list SHA-256: {expected_cell_site_hash}",
                log_text,
            )
            self.assertIn("Site ID: Start_eNodeB", log_text)
            self.assertIn("Site ID: E/G NodeB ID", log_text)
            self.assertIn("Original rows matched to cell site list: 1", log_text)
            self.assertIn(
                "Mapped-equivalent duplicate keys collapsed: 2", log_text
            )
            self.assertIn("Redundant cell site rows collapsed: 3", log_text)
            self.assertIn(
                "Unreferenced conflicting duplicate keys ignored: 1",
                log_text,
            )
            self.assertIn(
                "Original source rows unmatched in cell site list: None",
                log_text,
            )
            self.assertIn("Latitude values from cell site list: 1", log_text)
            self.assertIn("Reference cell site layer: Enabled", log_text)
            self.assertIn("Nearby cell site radius (miles): 25.0", log_text)
            self.assertIn("Reference cell site source: cell site list", log_text)
            self.assertIn("Reference cell sites considered: 12", log_text)
            self.assertIn("Static reference cell sites generated: 5", log_text)
            self.assertIn("Marker rows accepted: 3", log_text)
            self.assertIn("Static markers generated: 3", log_text)
            self.assertIn("Marker list 1: markers.csv", log_text)
            self.assertIn(
                f"Marker list 1 SHA-256: {window.calculate_file_sha256(marker_path)}",
                log_text,
            )


if __name__ == "__main__":
    unittest.main()