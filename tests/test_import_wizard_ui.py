"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
from openpyxl import Workbook
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

from import_wizard import (
    FIXED_UTC_OFFSETS,
    ImportWizardDialog,
    NAMED_TIMEZONE_CHOICES,
    SourceFileLoadWorker,
)
from kml_generator import KMLGenerator


class ImportWizardDialogUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_timezone_defaults_and_target_no_change_option(self):
        dialog = ImportWizardDialog()
        source_items = [dialog.source_timezone_combo.itemText(i) for i in range(dialog.source_timezone_combo.count())]
        target_items = [dialog.target_timezone_combo.itemText(i) for i in range(dialog.target_timezone_combo.count())]

        self.assertEqual("Fixed UTC+00:00", dialog.source_timezone_combo.currentText())
        self.assertEqual("No Change", dialog.target_timezone_combo.currentText())
        self.assertEqual((None, None), dialog.timezone_selection(dialog.target_timezone_combo))
        self.assertEqual(source_items, target_items[1:])
        self.assertEqual(len(NAMED_TIMEZONE_CHOICES) + len(FIXED_UTC_OFFSETS), len(source_items))
        self.assertNotIn("UTC (UTC+00:00)", source_items)
        self.assertIn("Fixed UTC+00:00", source_items)
        self.assertGreater(
            source_items.index("Fixed UTC+00:00"),
            source_items.index("Hawaii (UTC-10:00)"),
        )
        self.assertIn("US Eastern (UTC-05:00 / UTC-04:00 DST)", source_items)
        self.assertIn("Fixed UTC-05:00", source_items)
        self.assertIn("Fixed UTC+05:30", source_items)

    def test_new_source_resets_timezone_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "records.csv"
            pd.DataFrame([{
                "Timestamp": "2024-01-15 14:00:00",
                "Latitude": 43.15,
                "Longitude": -77.61,
            }]).to_csv(path, index=False)
            dialog = ImportWizardDialog()
            dialog.source_timezone_combo.setCurrentIndex(1)
            dialog.target_timezone_combo.setCurrentIndex(2)

            dialog.load_file(str(path), background=False)

            self.assertEqual(
                "Fixed UTC+00:00", dialog.source_timezone_combo.currentText()
            )
            self.assertEqual("No Change", dialog.target_timezone_combo.currentText())

    def test_timezone_choices_ignore_mouse_wheel(self):
        dialog = ImportWizardDialog()

        for combo in (dialog.source_timezone_combo, dialog.target_timezone_combo):
            starting_index = combo.currentIndex()
            wheel_event = Mock()

            combo.wheelEvent(wheel_event)

            self.assertEqual(starting_index, combo.currentIndex())
            wheel_event.ignore.assert_called_once_with()

    def test_source_loader_returns_excel_sheets_and_raw_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "records.xlsx"
            workbook = Workbook()
            workbook.active.title = "Records"
            workbook.active.append(["Timestamp", "Latitude", "Longitude"])
            workbook.active.append(["2024-01-15 14:00:00", 43.15, -77.61])
            workbook.create_sheet("Other")
            workbook.save(path)

            result = SourceFileLoadWorker.read_source(path)

            self.assertEqual(["Records", "Other"], result['sheet_names'])
            self.assertEqual("Records", result['sheet_name'])
            self.assertEqual(
                ["Timestamp", "Latitude", "Longitude"],
                result['raw_dataframe'].iloc[0].tolist(),
            )

    def test_dialog_loads_source_in_background_with_busy_progress(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "records.csv"
            pd.DataFrame([{
                "Timestamp": "2024-01-15 14:00:00",
                "Latitude": 43.15,
                "Longitude": -77.61,
            }]).to_csv(path, index=False)
            dialog = ImportWizardDialog()
            loading_finished = QSignalSpy(dialog.source_loading_finished)
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
                dialog.load_file(str(path))
                while not reader_started.is_set():
                    self.app.processEvents()

                heartbeat = []
                QTimer.singleShot(0, lambda: heartbeat.append(True))
                self.app.processEvents()

                self.assertEqual([True], heartbeat)
                self.assertFalse(dialog.source_load_progress.isHidden())
                self.assertFalse(dialog.header_row_spinbox.isEnabled())
                release_reader.set()
                self.assertTrue(loading_finished.wait(5000))
            self.app.processEvents()
            self.assertEqual(1, len(dialog.source_dataframe))
            self.assertTrue(dialog.source_load_progress.isHidden())
            self.assertTrue(dialog.header_row_spinbox.isEnabled())

    def test_numeric_date_order_and_filter_display_formats(self):
        dialog = ImportWizardDialog()
        labels = [label.text() for label in dialog.findChildren(type(dialog.mapping_note))]

        self.assertIn("Date format in source records:", labels)
        self.assertIn(
            "Choose the date order shown in the mapped source timestamp. "
            "A likely order is selected automatically; confirm it against the source records.",
            labels,
        )
        self.assertEqual(
            "Year-Month-Day (YYYY-MM-DD or YYYY/MM/DD)",
            dialog.date_order_combo.itemText(0),
        )
        self.assertEqual(
            "Year-Day-Month (YYYY-DD-MM or YYYY/DD/MM)",
            dialog.date_order_combo.itemText(1),
        )
        self.assertEqual(['YMD', 'YDM', 'MDY', 'DMY'], [
            dialog.date_order_combo.itemData(index)
            for index in range(dialog.date_order_combo.count())
        ])
        self.assertEqual("MM/dd/yyyy", dialog.filter_start_edit.displayFormat())
        self.assertEqual("MM/dd/yyyy", dialog.filter_end_edit.displayFormat())

        dialog.date_order_combo.setCurrentIndex(
            dialog.date_order_combo.findData('YMD')
        )
        self.assertEqual("yyyy-MM-dd", dialog.filter_start_edit.displayFormat())

        dialog.filter_enabled_checkbox.setChecked(True)
        dialog.filter_exact_times_checkbox.setChecked(True)
        self.assertEqual("yyyy-MM-dd h:mm:ss AP", dialog.filter_start_edit.displayFormat())
        self.assertEqual("yyyy-MM-dd h:mm:ss AP", dialog.filter_end_edit.displayFormat())

    def test_excel_header_row_8_preview_uses_1_based_physical_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "header_row_8.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Sheet1"
            for row_number in range(1, 8):
                sheet.append([f"metadata {row_number}"])
            sheet.append(["Timestamp", "Latitude", "Longitude", "Azimuth"])
            for idx in range(32):
                sheet.append([
                    f"2024-01-15 14:{idx:02d}:00",
                    43.15 + idx * 0.001,
                    -77.61 - idx * 0.001,
                    180,
                ])
            workbook.save(path)

            with patch.object(
                SourceFileLoadWorker,
                "read_source",
                wraps=SourceFileLoadWorker.read_source,
            ) as read_source:
                dialog = ImportWizardDialog()
                dialog._header_reload_timer.setInterval(0)
                dialog.load_file(str(path), background=False)
                with patch.object(
                    dialog, "populate_preview", wraps=dialog.populate_preview
                ) as populate_preview:
                    for header_row in range(2, 9):
                        dialog.header_row_spinbox.setValue(header_row)
                    self.app.processEvents()

            self.assertEqual(["Timestamp", "Latitude", "Longitude", "Azimuth"], list(dialog.source_dataframe.columns))
            self.assertEqual(0, dialog.source_dataframe.index[0])
            self.assertIn("Header row: 8", dialog.preview_label.text())
            self.assertEqual(25, dialog.preview_table.rowCount())
            self.assertEqual("9", dialog.preview_table.verticalHeaderItem(0).text())
            self.assertEqual(1, read_source.call_count)
            self.assertEqual(1, populate_preview.call_count)

    def test_mapped_timestamps_set_date_order_and_filter_endpoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "timestamp_range.csv"
            pd.DataFrame([
                {"Timestamp": "2024-01-15 14:00:00", "Latitude": 43.15, "Longitude": -77.61},
                {"Timestamp": "2024-01-16 15:15:00", "Latitude": 43.16, "Longitude": -77.62},
                {"Timestamp": "2024-01-17 16:30:00", "Latitude": 43.17, "Longitude": -77.63},
            ]).to_csv(path, index=False)

            dialog = ImportWizardDialog()
            dialog.load_file(str(path), background=False)

            self.assertEqual('YMD', dialog.date_order_combo.currentData())
            self.assertEqual("yyyy-MM-dd", dialog.filter_start_edit.displayFormat())
            self.assertEqual(
                "2024-01-15 14:00:00",
                dialog.filter_start_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
            )
            self.assertEqual(
                "2024-01-17 16:30:00",
                dialog.filter_end_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss"),
            )

    def test_timestamp_defaults_do_not_parse_every_source_row(self):
        dialog = ImportWizardDialog()
        row_count = 5000
        dialog.source_dataframe = pd.DataFrame({
            "Timestamp": ["2024-01-15 14:00:00"] * row_count,
            "Latitude": [43.15] * row_count,
            "Longitude": [-77.61] * row_count,
        })
        dialog.populate_mapping_options()

        parse_call_count = 0
        original_parse = KMLGenerator.parse_timestamp_to_kml

        def counting_parse(generator, timestamp):
            nonlocal parse_call_count
            parse_call_count += 1
            return original_parse(generator, timestamp)

        with patch.object(
            KMLGenerator, "parse_timestamp_to_kml", new=counting_parse
        ):
            dialog.populate_filter_range_from_source()

        self.assertEqual(2, parse_call_count)

    def test_year_day_month_filter_uses_detected_source_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "year_day_month.csv"
            pd.DataFrame([
                {"Timestamp": "2024-15-01 14:00:00", "Latitude": 43.15, "Longitude": -77.61},
                {"Timestamp": "2024-17-01 16:30:00", "Latitude": 43.17, "Longitude": -77.63},
            ]).to_csv(path, index=False)

            dialog = ImportWizardDialog()
            dialog.load_file(str(path), background=False)
            dialog.filter_enabled_checkbox.setChecked(True)
            dialog.filter_exact_times_checkbox.setChecked(True)
            filtered, metadata = dialog.apply_datetime_filter(
                dialog.build_normalized_dataframe(dialog.current_mappings())
            )

            self.assertEqual('YDM', dialog.date_order_combo.currentData())
            self.assertEqual("yyyy-dd-MM h:mm:ss AP", dialog.filter_start_edit.displayFormat())
            self.assertEqual(2, len(filtered))
            self.assertEqual(2, metadata['retained_rows'])

    def test_csv_preview_row_numbers_are_1_based_physical_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "records.csv"
            pd.DataFrame([
                {"Timestamp": "2024-01-15 14:00:00", "Latitude": 43.15, "Longitude": -77.61},
                {"Timestamp": "2024-01-15 14:15:00", "Latitude": 43.16, "Longitude": -77.62},
            ]).to_csv(path, index=False)

            dialog = ImportWizardDialog()
            dialog.load_file(str(path), background=False)
            dialog.header_row_spinbox.setValue(1)

            self.assertIn("Header row: 1", dialog.preview_label.text())
            self.assertEqual("2", dialog.preview_table.verticalHeaderItem(0).text())


if __name__ == "__main__":
    unittest.main()
