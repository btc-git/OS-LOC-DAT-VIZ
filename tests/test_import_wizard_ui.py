"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from PyQt6.QtWidgets import QApplication

from import_wizard import (
    FIXED_UTC_OFFSETS,
    ImportWizardDialog,
    NAMED_TIMEZONE_CHOICES,
)


class ImportWizardDialogUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_timezone_defaults_and_target_no_change_option(self):
        dialog = ImportWizardDialog()
        source_items = [dialog.source_timezone_combo.itemText(i) for i in range(dialog.source_timezone_combo.count())]
        target_items = [dialog.target_timezone_combo.itemText(i) for i in range(dialog.target_timezone_combo.count())]

        self.assertEqual("UTC (UTC+00:00)", dialog.source_timezone_combo.currentText())
        self.assertEqual("No Change", dialog.target_timezone_combo.currentText())
        self.assertEqual((None, None), dialog.timezone_selection(dialog.target_timezone_combo))
        self.assertEqual(source_items, target_items[1:])
        self.assertEqual(len(NAMED_TIMEZONE_CHOICES) + len(FIXED_UTC_OFFSETS), len(source_items))
        self.assertIn("UTC (UTC+00:00)", source_items)
        self.assertIn("US Eastern (UTC-05:00 / UTC-04:00 DST)", source_items)
        self.assertIn("Fixed UTC-05:00", source_items)
        self.assertIn("Fixed UTC+05:30", source_items)

    def test_numeric_date_order_and_filter_display_formats(self):
        dialog = ImportWizardDialog()
        labels = [label.text() for label in dialog.findChildren(type(dialog.mapping_note))]

        self.assertIn("Ambiguous slash/dash date order:", labels)
        self.assertEqual("MM/dd/yyyy", dialog.filter_start_edit.displayFormat())
        self.assertEqual("MM/dd/yyyy", dialog.filter_end_edit.displayFormat())

        dialog.filter_enabled_checkbox.setChecked(True)
        dialog.filter_exact_times_checkbox.setChecked(True)
        self.assertEqual("MM/dd/yyyy h:mm:ss AP", dialog.filter_start_edit.displayFormat())
        self.assertEqual("MM/dd/yyyy h:mm:ss AP", dialog.filter_end_edit.displayFormat())

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

            dialog = ImportWizardDialog()
            dialog.load_file(str(path))
            dialog.header_row_spinbox.setValue(8)
            dialog.reload_source()

            self.assertEqual(["Timestamp", "Latitude", "Longitude", "Azimuth"], list(dialog.source_dataframe.columns))
            self.assertIn("Header row: 8", dialog.preview_label.text())
            self.assertEqual(25, dialog.preview_table.rowCount())
            self.assertEqual("9", dialog.preview_table.verticalHeaderItem(0).text())

    def test_csv_preview_row_numbers_are_1_based_physical_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "records.csv"
            pd.DataFrame([
                {"Timestamp": "2024-01-15 14:00:00", "Latitude": 43.15, "Longitude": -77.61},
                {"Timestamp": "2024-01-15 14:15:00", "Latitude": 43.16, "Longitude": -77.62},
            ]).to_csv(path, index=False)

            dialog = ImportWizardDialog()
            dialog.load_file(str(path))
            dialog.header_row_spinbox.setValue(1)
            dialog.reload_source()

            self.assertIn("Header row: 1", dialog.preview_label.text())
            self.assertEqual("2", dialog.preview_table.verticalHeaderItem(0).text())


if __name__ == "__main__":
    unittest.main()
