"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import re
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import QDateTime, QTime, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QScrollArea, QWidget,
)

from kml_generator import KMLGenerator, TimestampResolutionError


NAMED_TIMEZONE_CHOICES = [
    ("UTC (UTC+00:00)", "UTC"),
    ("US Eastern (UTC-05:00 / UTC-04:00 DST)", "America/New_York"),
    ("US Central (UTC-06:00 / UTC-05:00 DST)", "America/Chicago"),
    ("US Mountain (UTC-07:00 / UTC-06:00 DST)", "America/Denver"),
    ("Arizona (UTC-07:00)", "America/Phoenix"),
    ("US Pacific (UTC-08:00 / UTC-07:00 DST)", "America/Los_Angeles"),
    ("Alaska (UTC-09:00 / UTC-08:00 DST)", "America/Anchorage"),
    ("Hawaii (UTC-10:00)", "Pacific/Honolulu"),
]

FIXED_UTC_OFFSETS = [
    -720, -660, -600, -570, -540, -480, -420, -360, -300, -240,
    -210, -180, -120, -60, 0, 60, 120, 180, 210, 240, 270, 300,
    330, 345, 360, 390, 420, 480, 525, 540, 570, 600, 630, 660,
    720, 765, 780, 825, 840,
]


def timezone_choice_data(timezone_name=None, fixed_offset_minutes=None,
                         no_change=False):
    return {
        'timezone_name': timezone_name,
        'offset_minutes': fixed_offset_minutes,
        'no_change': no_change,
    }


def fixed_offset_label(minutes):
    sign = '+' if minutes >= 0 else '-'
    hours, remainder = divmod(abs(minutes), 60)
    return f"Fixed UTC{sign}{hours:02d}:{remainder:02d}"


class ImportFileDropZone(QFrame):
    """Single drag/drop target with integrated file picker controls."""

    file_dropped = pyqtSignal(str)
    browse_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._drag_active = False
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)
        self.setObjectName("importDropZone")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        self.selected_label = QLabel("Selected: No source file selected")
        self.selected_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.selected_label.setStyleSheet("color: #e0e0e0; font-weight: bold;")
        layout.addWidget(self.selected_label)

        self.hint_label = QLabel("Drop CSV, XLS, or XLSX records here")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setStyleSheet("color: #9a9a9a;")
        layout.addWidget(self.hint_label)

        self.browse_button = QPushButton("Browse for File")
        self.browse_button.setMaximumWidth(180)
        self.browse_button.clicked.connect(self.browse_requested.emit)
        layout.addWidget(self.browse_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self._apply_style()

    def _apply_style(self):
        border_color = "#0078d4" if self._drag_active else "#555555"
        self.setStyleSheet(
            f"QFrame#importDropZone {{"
            f"background-color: #1e1e1e; border: 2px dashed {border_color};"
            f"border-radius: 8px; }}"
        )

    def set_selected_filename(self, filename):
        if filename:
            self.selected_label.setText(f"Selected: {filename}")
        else:
            self.selected_label.setText("Selected: No source file selected")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if any(url.isLocalFile() and url.toLocalFile().lower().endswith(('.csv', '.xls', '.xlsx'))
               for url in event.mimeData().urls()):
            self._drag_active = True
            self._apply_style()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._drag_active = False
        self._apply_style()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self._drag_active = False
        self._apply_style()
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith(('.csv', '.xls', '.xlsx')):
                self.file_dropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()


class ImportWizardDialog(QDialog):
    """Map columns from original records into the application's data model."""

    FIELD_ALIASES = {
        'Timestamp': ['timestamp', 'date time', 'datetime', 'start datetime', 'starttime',
                      'record open date time', 'msg send date', 'message send date'],
        'Date': ['date', 'conn date', 'connection date', 'start date'],
        'Time': ['time', 'conn time', 'conn time utc', 'connection time',
                 'connection time utc', 'start time'],
        'Latitude': ['latitude', 'lat', 'tower latitude', 'tower lat', 'cell latitude', 'cell lat'],
        'Longitude': ['longitude', 'lon', 'long', 'tower longitude', 'tower lon', 'cell longitude', 'cell lon'],
        'Azimuth': ['azimuth', 'bearing', 'direction'],
        'Distance': ['distance', 'range', 'distance m', 'distance meters'],
        'Accuracy': ['gps accuracy', 'accuracy', 'gps_accuracy'],
    }
    FIELD_LABELS = {
        'Timestamp': 'Timestamp (combined)',
        'Date': 'Date (separate)',
        'Time': 'Time (separate)',
        'Latitude': 'Latitude',
        'Longitude': 'Longitude',
        'Azimuth': 'Azimuth',
        'Distance': 'Distance from tower',
        'Accuracy': 'Location accuracy',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Original Records")
        self.setMinimumSize(760, 520)
        self.setSizeGripEnabled(True)
        self.source_path = None
        self.source_dataframe = None
        self.normalized_dataframe = None
        self.selected_data_type = None
        self.selected_timezone_name = None
        self.selected_offset_minutes = 0
        self.selected_source_timezone_name = None
        self.selected_source_offset_minutes = 0
        self.selected_target_timezone_name = None
        self.selected_target_offset_minutes = None
        self.selected_date_order = 'MDY'
        self.selected_mappings = {}
        self.selected_filter_metadata = {'enabled': False}
        self.selected_sheet_name = None
        self.selected_header_row = 1
        self.mapping_combos = {}
        self.mapping_labels = {}
        self.setup_ui()
        self.apply_initial_size()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        content_scroll = QScrollArea()
        content_scroll.setWidgetResizable(True)
        content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        source_group = QGroupBox("Source Records")
        source_layout = QVBoxLayout(source_group)
        self.drop_zone = ImportFileDropZone()
        self.drop_zone.file_dropped.connect(self.load_file)
        self.drop_zone.browse_requested.connect(self.browse_file)
        source_layout.addWidget(self.drop_zone)
        content_layout.addWidget(source_group)

        options_layout = QGridLayout()
        options_layout.addWidget(QLabel("Worksheet:"), 0, 0)
        self.sheet_combo = QComboBox()
        self.sheet_combo.currentIndexChanged.connect(self.reload_source)
        options_layout.addWidget(self.sheet_combo, 0, 1)
        options_layout.addWidget(QLabel("Header row:"), 0, 2)
        self.header_row_spinbox = QSpinBox()
        self.header_row_spinbox.setRange(1, 100)
        self.header_row_spinbox.setValue(1)
        options_layout.addWidget(self.header_row_spinbox, 0, 3)
        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(self.reload_source)
        options_layout.addWidget(reload_button, 0, 4)

        options_layout.addWidget(QLabel("Record type:"), 1, 0)
        self.record_type_combo = QComboBox()
        self.record_type_combo.addItem("Location Point", "Location Point")
        self.record_type_combo.addItem("Tower/Sector", "Tower/Sector")
        self.record_type_combo.addItem("Distance from Tower", "Distance from Tower")
        self.record_type_combo.currentIndexChanged.connect(self.update_mapping_requirements)
        options_layout.addWidget(self.record_type_combo, 1, 1, 1, 2)
        options_layout.addWidget(QLabel("Timestamp layout:"), 2, 0)
        self.timestamp_layout_combo = QComboBox()
        self.timestamp_layout_combo.addItem("One combined timestamp column", "combined")
        self.timestamp_layout_combo.addItem("Separate date and time columns", "separate")
        self.timestamp_layout_combo.currentIndexChanged.connect(self.update_mapping_requirements)
        options_layout.addWidget(self.timestamp_layout_combo, 2, 1, 1, 2)
        content_layout.addLayout(options_layout)

        mapping_group = QGroupBox("Column Mapping")
        mapping_layout = QGridLayout(mapping_group)
        mapping_layout.addWidget(QLabel("Application field"), 0, 0)
        mapping_layout.addWidget(QLabel("Source column"), 0, 1)
        for row, field in enumerate(self.FIELD_ALIASES, 1):
            field_label = QLabel(self.FIELD_LABELS[field])
            combo = QComboBox()
            combo.addItem("Not mapped", None)
            combo.currentIndexChanged.connect(self.update_preview_headers)
            self.mapping_labels[field] = field_label
            self.mapping_combos[field] = combo
            mapping_layout.addWidget(field_label, row, 0)
            mapping_layout.addWidget(combo, row, 1)
        self.mapping_note = QLabel("Map Timestamp, or map both Date and Time. Required fields are marked after selecting a record type.")
        self.mapping_note.setWordWrap(True)
        mapping_layout.addWidget(self.mapping_note, len(self.FIELD_ALIASES) + 1, 0, 1, 2)
        content_layout.addWidget(mapping_group)

        timezone_group = QGroupBox("Source Timestamp Interpretation")
        timezone_layout = QGridLayout(timezone_group)
        timezone_layout.addWidget(QLabel("Records are in:"), 0, 0)
        self.source_timezone_combo = QComboBox()
        timezone_layout.addWidget(self.source_timezone_combo, 0, 1)

        timezone_layout.addWidget(QLabel("Records are changed to:"), 0, 2)
        self.target_timezone_combo = QComboBox()
        timezone_layout.addWidget(self.target_timezone_combo, 0, 3)
        self.populate_timezone_choices(self.source_timezone_combo)
        self.populate_timezone_choices(
            self.target_timezone_combo, include_no_change=True
        )
        self.source_timezone_combo.currentIndexChanged.connect(self.update_timezone_controls)
        self.target_timezone_combo.currentIndexChanged.connect(self.update_timezone_controls)
        self.target_timezone_combo.setCurrentIndex(0)
        date_order_label = QLabel("Ambiguous slash/dash date order:")
        date_order_label.setToolTip(
            "Controls dates such as 04/10/2026 or 04-10-2026. "
            "Year-first and unambiguous dates are detected automatically."
        )
        timezone_layout.addWidget(date_order_label, 1, 0)
        self.date_order_combo = QComboBox()
        self.date_order_combo.addItem(
            "Month/Day/Year (MM/DD/YYYY or MM-DD-YYYY)", "MDY"
        )
        self.date_order_combo.addItem(
            "Day/Month/Year (DD/MM/YYYY or DD-MM-YYYY)", "DMY"
        )
        timezone_layout.addWidget(self.date_order_combo, 1, 1, 1, 3)
        timezone_note = QLabel(
            "Select the timezone used in the original records and the timezone you want those times displayed in. "
            "No Change keeps the source timezone for display. "
            "Daylight-saving adjustments are handled automatically from each record's date. "
            "Explicit timezone information in a mapped timestamp takes precedence."
        )
        timezone_note.setWordWrap(True)
        timezone_layout.addWidget(timezone_note, 2, 0, 1, 4)
        content_layout.addWidget(timezone_group)

        filter_group = QGroupBox("Date/Time Range Filter")
        filter_layout = QGridLayout(filter_group)
        self.filter_enabled_checkbox = QCheckBox("Import only records within this inclusive range")
        self.filter_enabled_checkbox.toggled.connect(self.update_filter_controls)
        filter_layout.addWidget(self.filter_enabled_checkbox, 0, 0, 1, 4)
        self.filter_exact_times_checkbox = QCheckBox("Use exact times")
        self.filter_exact_times_checkbox.toggled.connect(self.update_filter_controls)
        filter_layout.addWidget(self.filter_exact_times_checkbox, 0, 4)
        filter_layout.addWidget(QLabel("From:"), 1, 0)
        self.filter_start_edit = QDateTimeEdit()
        self.filter_start_edit.setCalendarPopup(True)
        self.filter_start_edit.setDisplayFormat("MM/dd/yyyy")
        self.filter_start_edit.setDateTime(
            QDateTime.currentDateTime().addDays(-1).toLocalTime()
        )
        self.filter_start_edit.setTime(QTime(0, 0, 0))
        filter_layout.addWidget(self.filter_start_edit, 1, 1)
        filter_layout.addWidget(QLabel("Through:"), 1, 2)
        self.filter_end_edit = QDateTimeEdit()
        self.filter_end_edit.setCalendarPopup(True)
        self.filter_end_edit.setDisplayFormat("MM/dd/yyyy")
        self.filter_end_edit.setDateTime(QDateTime.currentDateTime())
        self.filter_end_edit.setTime(QTime(23, 59, 59))
        filter_layout.addWidget(self.filter_end_edit, 1, 3)
        self.filter_preview_button = QPushButton("Check Matching Rows")
        self.filter_preview_button.clicked.connect(self.preview_filter_results)
        filter_layout.addWidget(self.filter_preview_button, 1, 4)
        filter_note = QLabel(
            "By default, the full start and end days are included. Exact times use the timestamp interpretation selected above."
        )
        filter_note.setWordWrap(True)
        filter_layout.addWidget(filter_note, 2, 0, 1, 4)
        self.filter_result_label = QLabel("Enable the filter to check how many rows will be retained.")
        self.filter_result_label.setWordWrap(True)
        filter_layout.addWidget(self.filter_result_label, 3, 0, 1, 5)
        content_layout.addWidget(filter_group)
        for combo in self.mapping_combos.values():
            combo.currentIndexChanged.connect(self.invalidate_filter_preview)
        for combo in (
            self.record_type_combo, self.timestamp_layout_combo,
            self.source_timezone_combo, self.target_timezone_combo,
            self.date_order_combo,
        ):
            combo.currentIndexChanged.connect(self.invalidate_filter_preview)
        self.filter_start_edit.dateTimeChanged.connect(self.invalidate_filter_preview)
        self.filter_end_edit.dateTimeChanged.connect(self.invalidate_filter_preview)
        self.filter_exact_times_checkbox.toggled.connect(self.invalidate_filter_preview)
        self.update_filter_controls()

        self.preview_table = QTableWidget()
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.horizontalHeader().setMinimumHeight(48)
        self.preview_table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                alternate-background-color: #292929;
                color: #ffffff;
                gridline-color: #555555;
            }
            QTableWidget::item:selected {
                background-color: #0078d4;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #404040;
                color: #ffffff;
                border: 0;
                border-right: 1px solid #666666;
                border-bottom: 1px solid #666666;
                padding: 5px;
            }
            QTableCornerButton::section {
                background-color: #404040;
                border: 1px solid #666666;
            }
        """)
        self.preview_label = QLabel(
            "Source Preview - first 25 data rows from the selected file. Each header shows how the source column maps into the application."
        )
        self.preview_label.setWordWrap(True)
        content_layout.addWidget(self.preview_label)
        self.preview_table.setMinimumHeight(180)
        content_layout.addWidget(self.preview_table, 1)

        content_scroll.setWidget(content_container)
        layout.addWidget(content_scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import Records")
        buttons.accepted.connect(self.accept_import)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.update_mapping_requirements()
        self.update_timezone_controls()

    def apply_initial_size(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(980, 720)
            return

        available = screen.availableGeometry()
        width = min(980, max(self.minimumWidth(), available.width() - 80))
        height = min(720, max(self.minimumHeight(), available.height() - 80))
        self.resize(width, height)

    @staticmethod
    def normalize_name(value):
        return re.sub(r'[^a-z0-9]+', ' ', str(value).lower()).strip()

    def populate_timezone_choices(self, combo, include_no_change=False):
        combo.clear()
        if include_no_change:
            combo.addItem(
                "No Change",
                timezone_choice_data(no_change=True),
            )
        for label, timezone_name in NAMED_TIMEZONE_CHOICES:
            combo.addItem(label, timezone_choice_data(timezone_name=timezone_name))
        for minutes in FIXED_UTC_OFFSETS:
            combo.addItem(
                fixed_offset_label(minutes),
                timezone_choice_data(fixed_offset_minutes=minutes),
            )

    @staticmethod
    def timezone_selection(combo):
        selection = combo.currentData() or {}
        if selection.get('no_change'):
            return None, None
        timezone_name = selection.get('timezone_name')
        offset_minutes = selection.get('offset_minutes')
        if timezone_name is not None:
            return timezone_name, 0
        return None, int(offset_minutes if offset_minutes is not None else 0)

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Original Records", "", "Record Files (*.csv *.xls *.xlsx);;All Files (*)"
        )
        if file_path:
            self.load_file(file_path)

    def load_file(self, file_path):
        self.source_path = file_path
        self.drop_zone.set_selected_filename(Path(file_path).name)
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        try:
            if Path(file_path).suffix.lower() in ('.xls', '.xlsx'):
                with pd.ExcelFile(file_path) as workbook:
                    self.sheet_combo.addItems(workbook.sheet_names)
                self.sheet_combo.setEnabled(True)
            else:
                self.sheet_combo.addItem("CSV")
                self.sheet_combo.setEnabled(False)
        except Exception as error:
            QMessageBox.critical(self, "Import Error", f"Could not inspect the source file:\n\n{error}")
            self.source_path = None
            self.drop_zone.set_selected_filename(None)
        finally:
            self.sheet_combo.blockSignals(False)
        if self.source_path:
            self.reload_source()

    def reload_source(self):
        if not self.source_path:
            return
        try:
            header_row = self.header_row_spinbox.value() - 1
            suffix = Path(self.source_path).suffix.lower()
            if suffix == '.csv':
                self.source_dataframe = pd.read_csv(self.source_path, header=header_row)
            else:
                self.source_dataframe = pd.read_excel(
                    self.source_path, sheet_name=self.sheet_combo.currentText(), header=header_row
                )
            self.populate_mapping_options()
            self.populate_preview()
            self.detect_record_type()
        except Exception as error:
            self.source_dataframe = None
            QMessageBox.critical(self, "Import Error", f"Could not read the selected data:\n\n{error}")

    def populate_mapping_options(self):
        columns = [str(column) for column in self.source_dataframe.columns]
        normalized = {self.normalize_name(column): column for column in columns}
        for field, combo in self.mapping_combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Not mapped", None)
            for column in columns:
                combo.addItem(column, column)
            for alias in self.FIELD_ALIASES[field]:
                matching_column = normalized.get(self.normalize_name(alias))
                if matching_column is not None:
                    combo.setCurrentIndex(combo.findData(matching_column))
                    break
            combo.blockSignals(False)

        if self.mapping_combos['Timestamp'].currentData() is not None:
            self.mapping_combos['Date'].setCurrentIndex(0)
            self.mapping_combos['Time'].setCurrentIndex(0)
            self.timestamp_layout_combo.setCurrentIndex(
                self.timestamp_layout_combo.findData('combined')
            )
        elif (self.mapping_combos['Date'].currentData() is not None and
              self.mapping_combos['Time'].currentData() is not None):
            self.timestamp_layout_combo.setCurrentIndex(
                self.timestamp_layout_combo.findData('separate')
            )
        self.update_mapping_requirements()

    def populate_preview(self):
        preview = self.source_dataframe.head(25)
        self.preview_table.setRowCount(len(preview))
        self.preview_table.setColumnCount(len(preview.columns))
        header_row = self.header_row_spinbox.value()
        first_data_row = header_row + 1
        for row_index, (_, row) in enumerate(preview.iterrows()):
            for column_index, value in enumerate(row):
                self.preview_table.setItem(row_index, column_index, QTableWidgetItem("" if pd.isna(value) else str(value)))
            self.preview_table.setVerticalHeaderItem(
                row_index, QTableWidgetItem(str(first_data_row + row_index))
            )
        self.preview_label.setText(
            "Source Preview - first 25 data rows from the selected file "
            f"(Header row: {header_row}). Each header shows how the source column maps into the application."
        )
        self.update_preview_headers()
        self.preview_table.resizeColumnsToContents()

    def update_preview_headers(self):
        """Show live source-to-application assignments above previewed values."""
        if self.source_dataframe is None or not hasattr(self, 'preview_table'):
            return

        active_fields = self.active_mapping_fields()
        source_mappings = {}
        for field, combo in self.mapping_combos.items():
            source_column = combo.currentData()
            if field in active_fields and source_column:
                source_mappings[source_column] = self.FIELD_LABELS[field]

        for column_index, source_column in enumerate(self.source_dataframe.columns):
            source_name = str(source_column)
            mapped_field = source_mappings.get(source_name, "Not mapped")
            header_item = QTableWidgetItem(
                f"Source: {source_name}\nMapped to: {mapped_field}"
            )
            header_item.setToolTip(
                f"Source column: {source_name}\nApplication field: {mapped_field}"
            )
            self.preview_table.setHorizontalHeaderItem(column_index, header_item)

    def detect_record_type(self):
        if self.mapping_combos['Distance'].currentData() is not None:
            index = self.record_type_combo.findData("Distance from Tower")
        elif self.mapping_combos['Azimuth'].currentData() is not None:
            index = self.record_type_combo.findData("Tower/Sector")
        else:
            index = self.record_type_combo.findData("Location Point")
        self.record_type_combo.setCurrentIndex(index)

    def update_mapping_requirements(self):
        data_type = self.record_type_combo.currentData()
        timestamp_layout = self.timestamp_layout_combo.currentData()
        active_fields = {'Latitude', 'Longitude'}
        if timestamp_layout == 'separate':
            active_fields.update({'Date', 'Time'})
            timestamp_requirement = 'Date and Time'
        else:
            active_fields.add('Timestamp')
            timestamp_requirement = 'Timestamp (combined)'

        required = ['Latitude', 'Longitude']
        note = ""
        if data_type == 'Tower/Sector':
            active_fields.add('Azimuth')
            note = "Azimuth is optional; when omitted, a 360-degree visualization is created."
        if data_type == 'Distance from Tower':
            active_fields.update({'Azimuth', 'Distance'})
            required.append('Distance')
            note = "Azimuth is optional. Band thickness is configured later in the main Settings tab, not mapped from a source column."
        elif data_type == 'Location Point':
            active_fields.add('Accuracy')
            note = "Location accuracy is optional; the configured default is used when it is missing."

        for field in self.FIELD_ALIASES:
            visible = field in active_fields
            self.mapping_labels[field].setVisible(visible)
            self.mapping_combos[field].setVisible(visible)

        self.mapping_note.setText(
            f"Required: {', '.join(required)}, plus {timestamp_requirement}. {note}"
        )
        self.update_preview_headers()

    def active_mapping_fields(self):
        """Return fields applicable to the selected record and timestamp layouts."""
        fields = {'Latitude', 'Longitude'}
        if self.timestamp_layout_combo.currentData() == 'separate':
            fields.update({'Date', 'Time'})
        else:
            fields.add('Timestamp')

        data_type = self.record_type_combo.currentData()
        if data_type == 'Tower/Sector':
            fields.add('Azimuth')
        elif data_type == 'Distance from Tower':
            fields.update({'Azimuth', 'Distance'})
        else:
            fields.add('Accuracy')
        return fields

    def update_timezone_controls(self):
        # Both source and target timezone selectors are always available.
        return

    def update_filter_controls(self):
        enabled = self.filter_enabled_checkbox.isChecked()
        exact_times = enabled and self.filter_exact_times_checkbox.isChecked()
        self.filter_exact_times_checkbox.setEnabled(enabled)
        self.filter_start_edit.setEnabled(enabled)
        self.filter_end_edit.setEnabled(enabled)
        self.filter_preview_button.setEnabled(enabled)
        display_format = "MM/dd/yyyy h:mm:ss AP" if exact_times else "MM/dd/yyyy"
        self.filter_start_edit.setDisplayFormat(display_format)
        self.filter_end_edit.setDisplayFormat(display_format)
        if not enabled:
            self.filter_result_label.setText("Enable the filter to check how many rows will be retained.")

    def invalidate_filter_preview(self):
        if self.filter_enabled_checkbox.isChecked():
            self.filter_result_label.setText("Filter settings changed. Check matching rows again.")

    def current_filter_boundaries(self):
        """Return filter boundaries, expanding date-only selections to full days."""
        start_datetime = self.filter_start_edit.dateTime()
        end_datetime = self.filter_end_edit.dateTime()
        if not self.filter_exact_times_checkbox.isChecked():
            start_datetime.setTime(QTime(0, 0, 0))
            end_datetime.setTime(QTime(23, 59, 59))
        return (
            start_datetime.toString("yyyy-MM-dd HH:mm:ss"),
            end_datetime.toString("yyyy-MM-dd HH:mm:ss"),
        )

    def current_mappings(self):
        """Return mappings that are active for the selected import layouts."""
        active_fields = self.active_mapping_fields()
        return {
            field: combo.currentData()
            for field, combo in self.mapping_combos.items()
            if field in active_fields
        }

    def build_normalized_dataframe(self, mappings):
        """Build the in-memory application columns from source mappings."""
        normalized = pd.DataFrame(index=self.source_dataframe.index)
        for field, source_column in mappings.items():
            if source_column:
                target_field = field
                if field == 'Time' and 'utc' in self.normalize_name(source_column).split():
                    target_field = 'Time (UTC)'
                normalized[target_field] = self.source_dataframe[source_column]

        timestamp_source = mappings.get('Timestamp')
        if timestamp_source and 'utc' in self.normalize_name(timestamp_source).split():
            normalized['Timestamp'] = normalized['Timestamp'].map(
                lambda value: value if pd.isna(value) else f"{value} UTC"
            )
        return normalized

    def preview_filter_results(self):
        """Show timestamp and coordinate counts before accepting the import."""
        if self.source_dataframe is None:
            QMessageBox.warning(self, "No Records", "Select a source file before checking the filter.")
            return
        mappings = self.current_mappings()
        timestamp_fields = ('Date', 'Time') if self.timestamp_layout_combo.currentData() == 'separate' else ('Timestamp',)
        required_fields = ('Latitude', 'Longitude', *timestamp_fields)
        if any(not mappings.get(field) for field in required_fields):
            QMessageBox.warning(self, "Incomplete Mapping", "Map the timestamp, latitude, and longitude fields before checking the filter.")
            return

        normalized = self.build_normalized_dataframe(mappings)
        try:
            filtered, metadata = self.apply_datetime_filter(normalized)
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Date/Time Filter", str(error))
            return

        self.filter_result_label.setText(
            f"{metadata['retained_rows']} of {metadata['input_rows']} rows match the time range. "
            f"{metadata['valid_coordinate_rows']} matching "
            f"{'row has' if metadata['valid_coordinate_rows'] == 1 else 'rows have'} valid mapped coordinates; "
            f"{metadata['invalid_coordinate_rows']} "
            f"{'does' if metadata['invalid_coordinate_rows'] == 1 else 'do'} not. "
            f"{metadata['unparseable_rows']} timestamps could not be evaluated."
        )

    def apply_datetime_filter(self, normalized):
        """Return rows within the selected inclusive range and audit metadata."""
        if not self.filter_enabled_checkbox.isChecked():
            return normalized, {'enabled': False}

        settings = {
            'source_utc_offset_minutes': self.timezone_selection(self.source_timezone_combo)[1],
            'source_timezone_name': self.timezone_selection(self.source_timezone_combo)[0],
            'source_date_order': self.date_order_combo.currentData(),
        }
        parser = KMLGenerator(self.source_path, self.record_type_combo.currentData(), settings)
        start_source, end_source = self.current_filter_boundaries()

        try:
            start_kml, _ = parser.parse_timestamp_to_kml(start_source)
            end_kml, _ = parser.parse_timestamp_to_kml(end_source)
        except TimestampResolutionError as error:
            raise ValueError(f"The selected filter boundary is not a unique local time: {error}") from error

        if not start_kml or not end_kml:
            raise ValueError("The selected date/time range could not be interpreted.")
        if start_kml > end_kml:
            raise ValueError("The start of the date/time range must not be after the end.")

        retained_indexes = []
        unparseable_count = 0
        for row_index, row in normalized.iterrows():
            try:
                timestamp = parser.get_timestamp_value(row)
                record_kml, _ = parser.parse_timestamp_to_kml(timestamp)
            except TimestampResolutionError:
                record_kml = None
            if not record_kml:
                unparseable_count += 1
            elif start_kml <= record_kml <= end_kml:
                retained_indexes.append(row_index)

        filtered = normalized.loc[retained_indexes].copy()
        valid_coordinate_rows = sum(
            parser.get_valid_coordinates(row) is not None
            for _, row in filtered.iterrows()
        )
        metadata = {
            'enabled': True,
            'exact_times': self.filter_exact_times_checkbox.isChecked(),
            'start_source': start_source,
            'end_source': end_source,
            'start_utc': start_kml,
            'end_utc': end_kml,
            'input_rows': len(normalized),
            'retained_rows': len(filtered),
            'excluded_rows': len(normalized) - len(filtered),
            'unparseable_rows': unparseable_count,
            'valid_coordinate_rows': valid_coordinate_rows,
            'invalid_coordinate_rows': len(filtered) - valid_coordinate_rows,
        }
        return filtered, metadata

    def accept_import(self):
        if self.source_dataframe is None:
            QMessageBox.warning(self, "No Records", "Select a source file before importing.")
            return

        mappings = self.current_mappings()
        required = ['Latitude', 'Longitude']
        data_type = self.record_type_combo.currentData()
        if data_type == 'Distance from Tower':
            required.append('Distance')

        missing = [field for field in required if not mappings[field]]
        if self.timestamp_layout_combo.currentData() == 'separate':
            has_timestamp = bool(mappings.get('Date') and mappings.get('Time'))
        else:
            has_timestamp = bool(mappings.get('Timestamp'))
        if not has_timestamp:
            missing.append('Timestamp or Date + Time')
        if missing:
            QMessageBox.warning(self, "Incomplete Mapping", f"Map the following required fields:\n\n{', '.join(missing)}")
            return

        selected_columns = [column for column in mappings.values() if column]
        if len(selected_columns) != len(set(selected_columns)):
            QMessageBox.warning(self, "Duplicate Mapping", "Each source column can be mapped to only one application field.")
            return

        normalized = self.build_normalized_dataframe(mappings)

        try:
            normalized, filter_metadata = self.apply_datetime_filter(normalized)
        except ValueError as error:
            QMessageBox.warning(self, "Invalid Date/Time Filter", str(error))
            return
        if filter_metadata['enabled'] and normalized.empty:
            QMessageBox.warning(
                self,
                "No Matching Records",
                "No records fall within the selected date/time range. Adjust the range and try again."
            )
            return

        self.normalized_dataframe = normalized
        self.selected_data_type = data_type
        source_timezone_name, source_offset_minutes = self.timezone_selection(self.source_timezone_combo)
        target_timezone_name, target_offset_minutes = self.timezone_selection(self.target_timezone_combo)
        self.selected_timezone_name = source_timezone_name
        self.selected_offset_minutes = source_offset_minutes
        self.selected_source_timezone_name = source_timezone_name
        self.selected_source_offset_minutes = source_offset_minutes
        self.selected_target_timezone_name = target_timezone_name
        self.selected_target_offset_minutes = target_offset_minutes
        self.selected_date_order = self.date_order_combo.currentData()
        self.selected_mappings = {
            field: source_column for field, source_column in mappings.items() if source_column
        }
        self.selected_filter_metadata = filter_metadata
        self.selected_sheet_name = (
            self.sheet_combo.currentText() if self.sheet_combo.isEnabled() else None
        )
        self.selected_header_row = self.header_row_spinbox.value()
        self.accept()