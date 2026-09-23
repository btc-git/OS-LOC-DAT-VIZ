"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from PyQt6.QtCore import QDateTime, QThread, QTime, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QScrollArea, QWidget,
)

from kml_generator import KMLGenerator, TimestampResolutionError


NAMED_TIMEZONE_CHOICES = [
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


class SourceFileLoadWorker(QThread):
    """Read source-file metadata or records without blocking the Qt UI thread."""

    result_ready = pyqtSignal(object)
    load_error = pyqtSignal(str)

    def __init__(self, file_path, sheet_name=None, header_row=0,
                 inspect_only=False, parent=None):
        super().__init__(parent)
        self.file_path = str(file_path)
        self.sheet_name = sheet_name
        self.header_row = header_row
        self.inspect_only = inspect_only

    @staticmethod
    def read_source(file_path, sheet_name=None, header_row=0,
                    inspect_only=False):
        suffix = Path(file_path).suffix.lower()
        if inspect_only:
            if suffix == '.xlsx':
                dataframe = pd.read_excel(
                    file_path, nrows=1, engine='openpyxl'
                )
            elif suffix == '.xls':
                dataframe = pd.read_excel(file_path, nrows=1)
            elif suffix == '.csv':
                dataframe = pd.read_csv(file_path, nrows=1)
            else:
                raise ValueError(
                    f"Unsupported file format: {suffix}. Please use .csv, .xls, or .xlsx files."
                )
            return {
                'file_path': str(file_path),
                'dataframe': dataframe,
            }

        if suffix in ('.xls', '.xlsx'):
            with pd.ExcelFile(file_path) as workbook:
                sheet_names = list(workbook.sheet_names)
                selected_sheet = sheet_name or sheet_names[0]
                raw_dataframe = workbook.parse(
                    sheet_name=selected_sheet, header=None
                )
            return {
                'file_path': str(file_path),
                'sheet_names': sheet_names,
                'sheet_name': selected_sheet,
                'raw_dataframe': raw_dataframe,
                'dataframe': None,
            }

        if suffix == '.csv':
            return {
                'file_path': str(file_path),
                'sheet_names': ['CSV'],
                'sheet_name': 'CSV',
                'raw_dataframe': None,
                'dataframe': pd.read_csv(file_path, header=header_row),
            }

        raise ValueError(
            f"Unsupported file format: {suffix}. Please use .csv, .xls, or .xlsx files."
        )

    def run(self):
        try:
            result = self.read_source(
                self.file_path,
                sheet_name=self.sheet_name,
                header_row=self.header_row,
                inspect_only=self.inspect_only,
            )
            self.result_ready.emit(result)
        except Exception as error:
            self.load_error.emit(str(error))


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


class ScrollSafeComboBox(QComboBox):
    """Let the containing page scroll without changing the selected item."""

    def wheelEvent(self, event):
        event.ignore()


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

    source_loading_finished = pyqtSignal(bool)
    cell_site_loading_finished = pyqtSignal(bool)
    TIMESTAMP_EDGE_SCAN_LIMIT = 100
    CELL_SITE_ROW_AUDIT_LIMIT = 100
    CELL_SITE_CONFLICT_DISPLAY_LIMIT = 10

    FIELD_ALIASES = {
        'Timestamp': ['timestamp', 'date time', 'datetime', 'start datetime', 'starttime',
                      'record open date time', 'msg send date', 'message send date'],
        'Date': ['date', 'conn date', 'connection date', 'start date'],
        'Time': ['time', 'conn time', 'conn time utc', 'connection time',
                 'connection time utc', 'start time'],
        'Latitude': ['latitude', 'lat', 'tower latitude', 'tower lat', 'cell latitude', 'cell lat'],
        'Longitude': ['longitude', 'lon', 'long', 'tower longitude', 'tower lon', 'cell longitude', 'cell lon'],
        'Azimuth': ['azimuth', 'bearing', 'direction'],
        'Distance': [
            'distance', 'range', 'distance m', 'distance meters',
            'start timing advance miles',
        ],
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
    TOWER_FIELD_LABELS = {
        'Latitude': 'Cell tower/site latitude',
        'Longitude': 'Cell tower/site longitude',
    }
    ORIGINAL_KEY_ALIASES = {
        'Site ID': [
            'start enodeb', 'start e nodeb', 'start gnodeb', 'start g nodeb',
            'start nodeb', 'start site id', 'enodeb id', 'gnodeb id',
            'nodeb id', 'site id',
        ],
        'Sector ID': [
            'start sector', 'start cell', 'start cell id', 'sector id',
            'cell id', 'sector',
        ],
    }
    CELL_SITE_FIELD_ALIASES = {
        'Site ID': [
            'e g nodeb id', 'enodeb id', 'gnodeb id', 'nodeb id',
            'site id', 'site number',
        ],
        'Sector ID': ['cell id', 'sector id', 'sector', 'cell'],
        'Latitude': [
            'site lat', 'site latitude', 'latitude', 'lat', 'tower latitude',
            'tower lat', 'cell latitude', 'cell lat',
        ],
        'Longitude': [
            'site long', 'site longitude', 'longitude', 'lon', 'long',
            'tower longitude', 'tower lon', 'cell longitude', 'cell lon',
        ],
        'Azimuth': ['azimuth', 'bearing', 'direction'],
    }
    CELL_SITE_FIELD_LABELS = {
        'Site ID': 'Site / Node ID',
        'Sector ID': 'Sector / Cell ID',
        'Latitude': 'Cell tower/site latitude',
        'Longitude': 'Cell tower/site longitude',
        'Azimuth': 'Sector azimuth',
    }
    CELL_SITE_POLICIES = [
        (
            'Cell site list only; unmatched values remain blank',
            'cell_site_only',
        ),
    ]

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
        self.selected_cell_site_metadata = {'enabled': False}
        self.reference_sites_dataframe = None
        self.selected_sheet_name = None
        self.selected_header_row = 1
        self.mapping_combos = {}
        self.mapping_labels = {}
        self.original_key_mapping_combos = {}
        self.cell_site_mapping_combos = {}
        self.cell_site_original_field_labels = {}
        self._cached_source_key = None
        self._cached_raw_dataframe = None
        self.cell_site_path = None
        self.cell_site_dataframe = None
        self.selected_cell_site_sheet_name = None
        self.selected_cell_site_header_row = 1
        self._cached_cell_site_key = None
        self._cached_cell_site_raw_dataframe = None
        self._reloading_source = False
        self._source_loader = None
        self._cell_site_loader = None
        self._source_load_token = 0
        self._cell_site_load_token = 0
        self._source_loading = False
        self._cell_site_loading = False
        self._background_loading_enabled = True
        self._cell_site_background_loading_enabled = True
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
        self.source_load_status = QLabel("Reading records...")
        self.source_load_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_load_status.setVisible(False)
        source_layout.addWidget(self.source_load_status)
        self.source_load_progress = QProgressBar()
        self.source_load_progress.setRange(0, 0)
        self.source_load_progress.setTextVisible(False)
        self.source_load_progress.setVisible(False)
        source_layout.addWidget(self.source_load_progress)
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
        self.header_row_spinbox.setToolTip(
            "Changing the header row reloads the source preview automatically."
        )
        self._header_reload_timer = QTimer(self)
        self._header_reload_timer.setSingleShot(True)
        self._header_reload_timer.setInterval(250)
        self._header_reload_timer.timeout.connect(self.reload_source)
        self.header_row_spinbox.valueChanged.connect(
            lambda _value: self._header_reload_timer.start()
        )
        options_layout.addWidget(self.header_row_spinbox, 0, 3)

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
        self.mapping_group = mapping_group
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

        timezone_group = QGroupBox("Timestamp Interpretation and Display")
        self.timezone_group = timezone_group
        timezone_layout = QGridLayout(timezone_group)
        timezone_layout.addWidget(QLabel("Source timestamps are in:"), 0, 0)
        self.source_timezone_combo = ScrollSafeComboBox()
        timezone_layout.addWidget(self.source_timezone_combo, 0, 1)

        timezone_layout.addWidget(QLabel("Display timestamps as:"), 0, 2)
        self.target_timezone_combo = ScrollSafeComboBox()
        timezone_layout.addWidget(self.target_timezone_combo, 0, 3)
        self.populate_timezone_choices(self.source_timezone_combo)
        self.populate_timezone_choices(
            self.target_timezone_combo, include_no_change=True
        )
        self.reset_timezone_defaults()
        self.source_timezone_combo.currentIndexChanged.connect(self.update_timezone_controls)
        self.target_timezone_combo.currentIndexChanged.connect(self.update_timezone_controls)
        date_order_label = QLabel("Date format in source records:")
        timezone_layout.addWidget(date_order_label, 1, 0)
        self.date_order_combo = QComboBox()
        self.date_order_combo.addItem(
            "Year-Month-Day (YYYY-MM-DD or YYYY/MM/DD)", "YMD"
        )
        self.date_order_combo.addItem(
            "Year-Day-Month (YYYY-DD-MM or YYYY/DD/MM)", "YDM"
        )
        self.date_order_combo.addItem(
            "Month-Day-Year (MM-DD-YYYY or MM/DD/YYYY)", "MDY"
        )
        self.date_order_combo.addItem(
            "Day-Month-Year (DD-MM-YYYY or DD/MM/YYYY)", "DMY"
        )
        self.date_order_combo.setCurrentIndex(
            self.date_order_combo.findData(self.selected_date_order)
        )
        timezone_layout.addWidget(self.date_order_combo, 1, 1, 1, 3)
        date_order_note = QLabel(
            "Choose the date order shown in the mapped source timestamp. "
            "A likely order is selected automatically; confirm it against the source records."
        )
        date_order_note.setWordWrap(True)
        timezone_layout.addWidget(date_order_note, 2, 1, 1, 3)
        timezone_note = QLabel(
            "Select the timezone used in the original records and the timezone you want those times displayed in. "
            "No Change keeps the source timezone for display. "
            "Daylight-saving adjustments are handled automatically from each record's date. "
            "Explicit timezone information in a mapped timestamp takes precedence."
        )
        timezone_note.setWordWrap(True)
        timezone_layout.addWidget(timezone_note, 3, 0, 1, 4)
        content_layout.addWidget(timezone_group)

        filter_group = QGroupBox("Date/Time Range Filter")
        self.filter_group = filter_group
        filter_layout = QGridLayout(filter_group)
        self.filter_enabled_checkbox = QCheckBox("Import only records within this inclusive range")
        self.filter_enabled_checkbox.toggled.connect(self.update_filter_controls)
        filter_layout.addWidget(self.filter_enabled_checkbox, 0, 0, 1, 4)
        self.filter_exact_times_checkbox = QCheckBox("Use exact times")
        self.filter_exact_times_checkbox.toggled.connect(self.update_filter_controls)
        filter_layout.addWidget(self.filter_exact_times_checkbox, 0, 4)
        self.filter_timezone_note = QLabel()
        self.filter_timezone_note.setWordWrap(True)
        filter_layout.addWidget(self.filter_timezone_note, 1, 0, 1, 5)
        filter_layout.addWidget(QLabel("From:"), 2, 0)
        self.filter_start_edit = QDateTimeEdit()
        self.filter_start_edit.setCalendarPopup(True)
        self.filter_start_edit.setDisplayFormat("MM/dd/yyyy")
        self.filter_start_edit.setDateTime(
            QDateTime.currentDateTime().addDays(-1).toLocalTime()
        )
        self.filter_start_edit.setTime(QTime(0, 0, 0))
        filter_layout.addWidget(self.filter_start_edit, 2, 1)
        filter_layout.addWidget(QLabel("Through:"), 2, 2)
        self.filter_end_edit = QDateTimeEdit()
        self.filter_end_edit.setCalendarPopup(True)
        self.filter_end_edit.setDisplayFormat("MM/dd/yyyy")
        self.filter_end_edit.setDateTime(QDateTime.currentDateTime())
        self.filter_end_edit.setTime(QTime(23, 59, 59))
        filter_layout.addWidget(self.filter_end_edit, 2, 3)
        self.filter_preview_button = QPushButton("Check Matching Rows")
        self.filter_preview_button.clicked.connect(self.preview_filter_results)
        filter_layout.addWidget(self.filter_preview_button, 2, 4)
        filter_note = QLabel(
            "When readable timestamps are mapped, this range is filled from the first and last readable records. "
            "By default, the full start and end days are included."
        )
        filter_note.setWordWrap(True)
        filter_layout.addWidget(filter_note, 3, 0, 1, 4)
        self.filter_result_label = QLabel("Enable the filter to check how many rows will be retained.")
        self.filter_result_label.setWordWrap(True)
        filter_layout.addWidget(self.filter_result_label, 4, 0, 1, 5)
        content_layout.addWidget(filter_group)
        for combo in self.mapping_combos.values():
            combo.currentIndexChanged.connect(self.invalidate_filter_preview)
        for field in ('Timestamp', 'Date', 'Time'):
            self.mapping_combos[field].currentIndexChanged.connect(
                self.refresh_timestamp_defaults
            )
        for combo in (
            self.record_type_combo, self.timestamp_layout_combo,
            self.source_timezone_combo, self.target_timezone_combo,
            self.date_order_combo,
        ):
            combo.currentIndexChanged.connect(self.invalidate_filter_preview)
        self.timestamp_layout_combo.currentIndexChanged.connect(
            self.refresh_timestamp_defaults
        )
        self.date_order_combo.currentIndexChanged.connect(
            lambda _index: self.update_filter_controls()
        )
        self.date_order_combo.currentIndexChanged.connect(
            self.populate_filter_range_from_source
        )
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

        self.cell_site_group = QGroupBox("Separate Cell Site List (Optional)")
        cell_site_layout = QVBoxLayout(self.cell_site_group)
        self.use_cell_site_list_checkbox = QCheckBox(
            "Use a separate cell site list for tower coordinates and azimuth"
        )
        self.use_cell_site_list_checkbox.toggled.connect(
            self.on_cell_site_enabled_changed
        )
        cell_site_layout.addWidget(self.use_cell_site_list_checkbox)

        self.cell_site_controls = QWidget()
        cell_site_controls_layout = QVBoxLayout(self.cell_site_controls)
        cell_site_controls_layout.setContentsMargins(0, 0, 0, 0)
        cell_site_controls_layout.setSpacing(8)

        self.cell_site_drop_zone = ImportFileDropZone()
        self.cell_site_drop_zone.setMinimumHeight(110)
        self.cell_site_drop_zone.selected_label.setText(
            "Selected: No cell site list selected"
        )
        self.cell_site_drop_zone.hint_label.setText(
            "Drop a CSV, XLS, or XLSX cell site list here"
        )
        self.cell_site_drop_zone.file_dropped.connect(self.load_cell_site_file)
        self.cell_site_drop_zone.browse_requested.connect(
            self.browse_cell_site_file
        )
        cell_site_controls_layout.addWidget(self.cell_site_drop_zone)

        self.cell_site_load_status = QLabel("Reading cell site list...")
        self.cell_site_load_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cell_site_load_status.setVisible(False)
        cell_site_controls_layout.addWidget(self.cell_site_load_status)
        self.cell_site_load_progress = QProgressBar()
        self.cell_site_load_progress.setRange(0, 0)
        self.cell_site_load_progress.setTextVisible(False)
        self.cell_site_load_progress.setVisible(False)
        cell_site_controls_layout.addWidget(self.cell_site_load_progress)

        cell_site_options_layout = QGridLayout()
        cell_site_options_layout.addWidget(QLabel("Worksheet:"), 0, 0)
        self.cell_site_sheet_combo = QComboBox()
        self.cell_site_sheet_combo.currentIndexChanged.connect(
            self.reload_cell_site_source
        )
        cell_site_options_layout.addWidget(self.cell_site_sheet_combo, 0, 1)
        cell_site_options_layout.addWidget(QLabel("Header row:"), 0, 2)
        self.cell_site_header_row_spinbox = QSpinBox()
        self.cell_site_header_row_spinbox.setRange(1, 100)
        self.cell_site_header_row_spinbox.setValue(1)
        self._cell_site_header_reload_timer = QTimer(self)
        self._cell_site_header_reload_timer.setSingleShot(True)
        self._cell_site_header_reload_timer.setInterval(250)
        self._cell_site_header_reload_timer.timeout.connect(
            self.reload_cell_site_source
        )
        self.cell_site_header_row_spinbox.valueChanged.connect(
            lambda _value: self._cell_site_header_reload_timer.start()
        )
        cell_site_options_layout.addWidget(
            self.cell_site_header_row_spinbox, 0, 3
        )
        cell_site_controls_layout.addLayout(cell_site_options_layout)

        cell_site_mapping_group = QGroupBox("Cell Site List Mapping")
        cell_site_mapping_layout = QGridLayout(cell_site_mapping_group)
        cell_site_mapping_layout.addWidget(QLabel("Mapping role"), 0, 0)
        cell_site_mapping_layout.addWidget(QLabel("Original records"), 0, 1)
        cell_site_mapping_layout.addWidget(QLabel("Cell site list"), 0, 2)
        for row, field in enumerate(('Site ID', 'Sector ID'), 1):
            original_combo = QComboBox()
            original_combo.addItem("Not mapped", None)
            cell_site_combo = QComboBox()
            cell_site_combo.addItem("Not mapped", None)
            cell_site_combo.currentIndexChanged.connect(
                self.update_cell_site_preview_headers
            )
            self.original_key_mapping_combos[field] = original_combo
            self.cell_site_mapping_combos[field] = cell_site_combo
            cell_site_mapping_layout.addWidget(
                QLabel(self.CELL_SITE_FIELD_LABELS[field]), row, 0
            )
            cell_site_mapping_layout.addWidget(original_combo, row, 1)
            cell_site_mapping_layout.addWidget(cell_site_combo, row, 2)

        for row, field in enumerate(
            ('Latitude', 'Longitude', 'Azimuth'), 3
        ):
            original_label = QLabel("Not used")
            original_label.setStyleSheet("color: #9a9a9a;")
            original_label.setToolTip(
                "This value comes from the separate cell site list."
            )
            cell_site_combo = QComboBox()
            cell_site_combo.addItem("Not mapped", None)
            cell_site_combo.currentIndexChanged.connect(
                self.update_cell_site_preview_headers
            )
            self.cell_site_mapping_combos[field] = cell_site_combo
            cell_site_mapping_layout.addWidget(
                QLabel(self.CELL_SITE_FIELD_LABELS[field]), row, 0
            )
            self.cell_site_original_field_labels[field] = original_label
            cell_site_mapping_layout.addWidget(original_label, row, 1)
            cell_site_mapping_layout.addWidget(cell_site_combo, row, 2)

        cell_site_mapping_note = QLabel(
            "Match one site/node ID and one sector/cell ID from the original "
            "records to the corresponding cell site list columns. Cell "
            "tower/site latitude and longitude are required; sector azimuth "
            "is optional."
        )
        cell_site_mapping_note.setWordWrap(True)
        cell_site_mapping_layout.addWidget(cell_site_mapping_note, 6, 0, 1, 3)
        cell_site_controls_layout.addWidget(cell_site_mapping_group)

        policy_layout = QHBoxLayout()
        policy_layout.addWidget(QLabel("Tower field source:"))
        self.cell_site_policy_combo = QComboBox()
        for label, value in self.CELL_SITE_POLICIES:
            self.cell_site_policy_combo.addItem(label, value)
        self.cell_site_policy_combo.setEnabled(False)
        self.cell_site_policy_combo.setToolTip(
            "Latitude, longitude, and azimuth are taken only from the cell site list."
        )
        policy_layout.addWidget(self.cell_site_policy_combo, 1)
        cell_site_controls_layout.addLayout(policy_layout)

        self.cell_site_preview_label = QLabel(
            "Cell Site List Preview - select a file to review its mapped columns."
        )
        self.cell_site_preview_label.setWordWrap(True)
        cell_site_controls_layout.addWidget(self.cell_site_preview_label)
        self.cell_site_preview_table = QTableWidget()
        self.cell_site_preview_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.cell_site_preview_table.setAlternatingRowColors(True)
        self.cell_site_preview_table.setMinimumHeight(150)
        self.cell_site_preview_table.setStyleSheet(
            self.preview_table.styleSheet()
        )
        cell_site_controls_layout.addWidget(self.cell_site_preview_table)
        cell_site_layout.addWidget(self.cell_site_controls)
        content_layout.addWidget(self.cell_site_group)

        content_scroll.setWidget(content_container)
        layout.addWidget(content_scroll, 1)

        self.dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Ok
        )
        self.dialog_buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import Records")
        self.dialog_buttons.accepted.connect(self.accept_import)
        self.dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(self.dialog_buttons)
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

    def application_field_label(self, field, data_type=None):
        data_type = data_type or self.record_type_combo.currentData()
        if data_type in ('Tower/Sector', 'Distance from Tower'):
            return self.TOWER_FIELD_LABELS.get(field, self.FIELD_LABELS[field])
        return self.FIELD_LABELS[field]

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

    def reset_timezone_defaults(self):
        """Start each newly selected record set in UTC without display conversion."""
        for index in range(self.source_timezone_combo.count()):
            selection = self.source_timezone_combo.itemData(index) or {}
            if (
                selection.get('timezone_name') is None
                and selection.get('offset_minutes') == 0
            ):
                self.source_timezone_combo.setCurrentIndex(index)
                break
        for index in range(self.target_timezone_combo.count()):
            selection = self.target_timezone_combo.itemData(index) or {}
            if selection.get('no_change'):
                self.target_timezone_combo.setCurrentIndex(index)
                break

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

    def effective_filter_timezone_selection(self):
        """Return the timezone used to interpret filter boundary controls."""
        target_timezone_name, target_offset_minutes = self.timezone_selection(
            self.target_timezone_combo
        )
        if target_timezone_name is not None or target_offset_minutes is not None:
            return (
                target_timezone_name,
                target_offset_minutes,
                self.target_timezone_combo.currentText(),
                'display',
            )

        source_timezone_name, source_offset_minutes = self.timezone_selection(
            self.source_timezone_combo
        )
        return (
            source_timezone_name,
            source_offset_minutes,
            self.source_timezone_combo.currentText(),
            'source',
        )

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Original Records", "", "Record Files (*.csv *.xls *.xlsx);;All Files (*)"
        )
        if file_path:
            self.load_file(file_path)

    def browse_cell_site_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Cell Site List",
            "",
            "Cell Site Lists (*.csv *.xls *.xlsx);;All Files (*)",
        )
        if file_path:
            self.load_cell_site_file(file_path)

    def load_cell_site_file(self, file_path, background=True):
        self.cell_site_path = file_path
        self.cell_site_dataframe = None
        self._cached_cell_site_key = None
        self._cached_cell_site_raw_dataframe = None
        self._cell_site_background_loading_enabled = background
        self.cell_site_drop_zone.set_selected_filename(Path(file_path).name)
        self.cell_site_preview_table.setRowCount(0)
        self.cell_site_preview_table.setColumnCount(0)
        self._load_cell_site_records(background=background)

    def _load_cell_site_records(self, sheet_name=None, background=True):
        """Load one cell site list worksheet independently of source records."""
        if not self.cell_site_path:
            return

        self._cell_site_load_token += 1
        token = self._cell_site_load_token
        header_row = self.cell_site_header_row_spinbox.value() - 1
        self.set_cell_site_loading(True)
        if not background:
            try:
                result = SourceFileLoadWorker.read_source(
                    self.cell_site_path,
                    sheet_name=sheet_name,
                    header_row=header_row,
                )
            except Exception as error:
                self.on_cell_site_load_error(str(error), token)
            else:
                self.on_cell_site_load_result(result, token)
            return

        worker = SourceFileLoadWorker(
            self.cell_site_path,
            sheet_name=sheet_name,
            header_row=header_row,
            parent=QApplication.instance(),
        )
        self._cell_site_loader = worker
        worker.result_ready.connect(
            lambda result, load_token=token: self.on_cell_site_load_result(
                result, load_token
            )
        )
        worker.load_error.connect(
            lambda message, load_token=token: self.on_cell_site_load_error(
                message, load_token
            )
        )
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(
            lambda load_worker=worker: self.on_cell_site_loader_finished(
                load_worker
            )
        )
        worker.start()

    def load_file(self, file_path, background=True):
        self.reset_timezone_defaults()
        self.source_path = file_path
        self.source_dataframe = None
        self._cached_source_key = None
        self._cached_raw_dataframe = None
        self._background_loading_enabled = background
        self.drop_zone.set_selected_filename(Path(file_path).name)
        self.preview_table.setRowCount(0)
        self.preview_table.setColumnCount(0)
        self._load_source_records(background=background)

    def _load_source_records(self, sheet_name=None, background=True):
        """Load one source worksheet, optionally on a background thread."""
        if not self.source_path:
            return

        self._source_load_token += 1
        token = self._source_load_token
        header_row = self.header_row_spinbox.value() - 1
        self.set_source_loading(True)
        if not background:
            try:
                result = SourceFileLoadWorker.read_source(
                    self.source_path,
                    sheet_name=sheet_name,
                    header_row=header_row,
                )
            except Exception as error:
                self.on_source_load_error(str(error), token)
            else:
                self.on_source_load_result(result, token)
            return

        worker = SourceFileLoadWorker(
            self.source_path,
            sheet_name=sheet_name,
            header_row=header_row,
            parent=QApplication.instance(),
        )
        self._source_loader = worker
        worker.result_ready.connect(
            lambda result, load_token=token: self.on_source_load_result(
                result, load_token
            )
        )
        worker.load_error.connect(
            lambda message, load_token=token: self.on_source_load_error(
                message, load_token
            )
        )
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(
            lambda load_worker=worker: self.on_source_loader_finished(
                load_worker
            )
        )
        worker.start()

    def set_source_loading(self, loading):
        """Show source-read progress and prevent edits against partial data."""
        self._source_loading = loading
        self.source_load_status.setVisible(loading)
        self.source_load_progress.setVisible(loading)
        self.drop_zone.setEnabled(not loading)
        self.header_row_spinbox.setEnabled(not loading)
        self.record_type_combo.setEnabled(not loading)
        self.timestamp_layout_combo.setEnabled(not loading)
        self.mapping_group.setEnabled(not loading)
        self.timezone_group.setEnabled(not loading)
        self.filter_group.setEnabled(not loading)
        self.preview_table.setEnabled(not loading)
        is_excel = bool(
            self.source_path and
            Path(self.source_path).suffix.lower() in ('.xls', '.xlsx')
        )
        self.sheet_combo.setEnabled(not loading and is_excel)
        self.update_import_button_enabled()

    def set_cell_site_loading(self, loading):
        """Show CSL-read progress and prevent edits against partial data."""
        self._cell_site_loading = loading
        self.cell_site_load_status.setVisible(loading)
        self.cell_site_load_progress.setVisible(loading)
        self.update_cell_site_controls()
        self.update_import_button_enabled()

    def update_import_button_enabled(self):
        if not hasattr(self, 'dialog_buttons'):
            return
        self.dialog_buttons.button(
            QDialogButtonBox.StandardButton.Ok
        ).setEnabled(
            not self._source_loading
            and not self._cell_site_loading
            and self.source_dataframe is not None
        )

    def on_source_load_result(self, result, token):
        """Apply records returned by the active source worker."""
        if token != self._source_load_token:
            return

        sheet_names = result['sheet_names']
        selected_sheet = result['sheet_name']
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        self.sheet_combo.addItems(sheet_names)
        self.sheet_combo.setCurrentIndex(
            self.sheet_combo.findText(selected_sheet)
        )
        self.sheet_combo.blockSignals(False)

        raw_dataframe = result['raw_dataframe']
        if raw_dataframe is not None:
            self._cached_source_key = (self.source_path, selected_sheet)
            self._cached_raw_dataframe = raw_dataframe
            self.source_dataframe = self.dataframe_from_header_row(
                raw_dataframe, self.header_row_spinbox.value() - 1
            )
        else:
            self._cached_source_key = None
            self._cached_raw_dataframe = None
            self.source_dataframe = result['dataframe']

        self.populate_loaded_source()
        self.set_source_loading(False)
        self.source_loading_finished.emit(True)

    def on_source_load_error(self, message, token):
        """Restore the dialog after a background source-read failure."""
        if token != self._source_load_token:
            return
        self.source_dataframe = None
        self.source_path = None
        self.drop_zone.set_selected_filename(None)
        self.set_source_loading(False)
        self.source_loading_finished.emit(False)
        QMessageBox.critical(
            self,
            "Import Error",
            f"Could not read the selected data:\n\n{message}",
        )

    def on_source_loader_finished(self, worker):
        """Release the completed source worker reference."""
        if self._source_loader is worker:
            self._source_loader = None

    def on_cell_site_load_result(self, result, token):
        """Apply the cell site list returned by the active worker."""
        if token != self._cell_site_load_token:
            return

        sheet_names = result['sheet_names']
        selected_sheet = result['sheet_name']
        self.cell_site_sheet_combo.blockSignals(True)
        self.cell_site_sheet_combo.clear()
        self.cell_site_sheet_combo.addItems(sheet_names)
        self.cell_site_sheet_combo.setCurrentIndex(
            self.cell_site_sheet_combo.findText(selected_sheet)
        )
        self.cell_site_sheet_combo.blockSignals(False)

        raw_dataframe = result['raw_dataframe']
        if raw_dataframe is not None:
            self._cached_cell_site_key = (
                self.cell_site_path,
                selected_sheet,
            )
            self._cached_cell_site_raw_dataframe = raw_dataframe
            self.cell_site_dataframe = self.dataframe_from_header_row(
                raw_dataframe, self.cell_site_header_row_spinbox.value() - 1
            )
        else:
            self._cached_cell_site_key = None
            self._cached_cell_site_raw_dataframe = None
            self.cell_site_dataframe = result['dataframe']

        self.populate_cell_site_mapping_options()
        self.populate_cell_site_preview()
        self.set_cell_site_loading(False)
        self.cell_site_loading_finished.emit(True)

    def on_cell_site_load_error(self, message, token):
        """Restore the CSL controls after a background read failure."""
        if token != self._cell_site_load_token:
            return
        self.cell_site_dataframe = None
        self.cell_site_path = None
        self.cell_site_drop_zone.set_selected_filename(None)
        self.cell_site_drop_zone.selected_label.setText(
            "Selected: No cell site list selected"
        )
        self.set_cell_site_loading(False)
        self.cell_site_loading_finished.emit(False)
        QMessageBox.critical(
            self,
            "Cell Site List Error",
            f"Could not read the selected cell site list:\n\n{message}",
        )

    def on_cell_site_loader_finished(self, worker):
        """Release the completed CSL worker reference."""
        if self._cell_site_loader is worker:
            self._cell_site_loader = None

    def populate_loaded_source(self):
        """Populate mappings and previews after source records are available."""
        self._reloading_source = True
        try:
            self.populate_mapping_options()
            self.populate_preview()
            self.detect_record_type()
        finally:
            self._reloading_source = False
        self.refresh_timestamp_defaults()

    def reload_source(self):
        if not self.source_path:
            return
        try:
            header_row = self.header_row_spinbox.value() - 1
            suffix = Path(self.source_path).suffix.lower()
            if suffix == '.csv':
                self._load_source_records(
                    background=self._background_loading_enabled
                )
                return

            sheet_name = self.sheet_combo.currentText()
            source_key = (self.source_path, sheet_name)
            if self._cached_source_key != source_key:
                self._load_source_records(
                    sheet_name=sheet_name,
                    background=self._background_loading_enabled,
                )
                return
            self.source_dataframe = self.dataframe_from_header_row(
                self._cached_raw_dataframe, header_row
            )
            self.populate_loaded_source()
        except Exception as error:
            self.source_dataframe = None
            QMessageBox.critical(self, "Import Error", f"Could not read the selected data:\n\n{error}")

    def reload_cell_site_source(self):
        if not self.cell_site_path:
            return
        try:
            header_row = self.cell_site_header_row_spinbox.value() - 1
            suffix = Path(self.cell_site_path).suffix.lower()
            if suffix == '.csv':
                self._load_cell_site_records(
                    background=self._cell_site_background_loading_enabled
                )
                return

            sheet_name = self.cell_site_sheet_combo.currentText()
            source_key = (self.cell_site_path, sheet_name)
            if self._cached_cell_site_key != source_key:
                self._load_cell_site_records(
                    sheet_name=sheet_name,
                    background=self._cell_site_background_loading_enabled,
                )
                return
            self.cell_site_dataframe = self.dataframe_from_header_row(
                self._cached_cell_site_raw_dataframe, header_row
            )
            self.populate_cell_site_mapping_options()
            self.populate_cell_site_preview()
        except Exception as error:
            self.cell_site_dataframe = None
            QMessageBox.critical(
                self,
                "Cell Site List Error",
                f"Could not read the selected cell site list:\n\n{error}",
            )

    @staticmethod
    def dataframe_from_header_row(raw_dataframe, header_row):
        """Apply an Excel header row without reparsing the workbook."""
        if header_row >= len(raw_dataframe):
            raise ValueError(
                f"Header row {header_row + 1} is beyond the available worksheet rows."
            )

        columns = []
        used_names = set()
        for column_index, value in enumerate(raw_dataframe.iloc[header_row]):
            base_name = (
                f"Unnamed: {column_index}"
                if pd.isna(value) or not str(value).strip()
                else str(value)
            )
            column_name = base_name
            duplicate_index = 1
            while column_name in used_names:
                column_name = f"{base_name}.{duplicate_index}"
                duplicate_index += 1
            columns.append(column_name)
            used_names.add(column_name)

        dataframe = raw_dataframe.iloc[header_row + 1:].copy(deep=False)
        dataframe.columns = columns
        dataframe.index = pd.RangeIndex(len(dataframe))
        return dataframe

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
        self.populate_original_key_mapping_options()
        self.update_mapping_requirements()

    def populate_original_key_mapping_options(self):
        """Populate record-side columns used to match the optional CSL."""
        if self.source_dataframe is None:
            return
        columns = [str(column) for column in self.source_dataframe.columns]
        self.populate_aliased_combos(
            self.original_key_mapping_combos,
            self.ORIGINAL_KEY_ALIASES,
            columns,
        )

    def populate_cell_site_mapping_options(self):
        """Populate and suggest CSL-side join and tower field mappings."""
        if self.cell_site_dataframe is None:
            return
        columns = [str(column) for column in self.cell_site_dataframe.columns]
        self.populate_aliased_combos(
            self.cell_site_mapping_combos,
            self.CELL_SITE_FIELD_ALIASES,
            columns,
        )

    def populate_aliased_combos(self, combos, aliases, columns):
        normalized = {
            self.normalize_name(column): column for column in columns
        }
        for field, combo in combos.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Not mapped", None)
            for column in columns:
                combo.addItem(column, column)
            for alias in aliases[field]:
                matching_column = normalized.get(self.normalize_name(alias))
                if matching_column is not None:
                    combo.setCurrentIndex(combo.findData(matching_column))
                    break
            combo.blockSignals(False)

    def populate_cell_site_preview(self):
        preview = self.cell_site_dataframe.head(25)
        self.cell_site_preview_table.setRowCount(len(preview))
        self.cell_site_preview_table.setColumnCount(len(preview.columns))
        header_row = self.cell_site_header_row_spinbox.value()
        first_data_row = header_row + 1
        for row_index, (_, row) in enumerate(preview.iterrows()):
            for column_index, value in enumerate(row):
                self.cell_site_preview_table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem("" if pd.isna(value) else str(value)),
                )
            self.cell_site_preview_table.setVerticalHeaderItem(
                row_index, QTableWidgetItem(str(first_data_row + row_index))
            )
        self.cell_site_preview_label.setText(
            "Cell Site List Preview - first 25 data rows "
            f"(Header row: {header_row})."
        )
        self.update_cell_site_preview_headers()
        self.cell_site_preview_table.resizeColumnsToContents()

    def update_cell_site_preview_headers(self):
        if self.cell_site_dataframe is None:
            return
        source_mappings = {
            combo.currentData(): self.CELL_SITE_FIELD_LABELS[field]
            for field, combo in self.cell_site_mapping_combos.items()
            if combo.currentData()
        }
        for column_index, source_column in enumerate(
            self.cell_site_dataframe.columns
        ):
            source_name = str(source_column)
            mapped_field = source_mappings.get(source_name, "Not mapped")
            item = QTableWidgetItem(
                f"Source: {source_name}\nMapped to: {mapped_field}"
            )
            item.setToolTip(
                f"Cell site list column: {source_name}\n"
                f"Mapping role: {mapped_field}"
            )
            self.cell_site_preview_table.setHorizontalHeaderItem(
                column_index, item
            )

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
                source_mappings[source_column] = self.application_field_label(
                    field
                )

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

        using_cell_site_list = self.cell_site_list_enabled()
        required = [] if using_cell_site_list else ['Latitude', 'Longitude']
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
            self.mapping_labels[field].setText(
                self.application_field_label(field, data_type)
            )
            self.mapping_labels[field].setVisible(visible)
            self.mapping_combos[field].setVisible(visible)
            supplied_by_cell_site = (
                using_cell_site_list
                and field in ('Latitude', 'Longitude', 'Azimuth')
            )
            self.mapping_labels[field].setEnabled(not supplied_by_cell_site)
            self.mapping_combos[field].setEnabled(not supplied_by_cell_site)
            self.mapping_combos[field].setToolTip(
                "Not used while a separate cell site list is enabled."
                if supplied_by_cell_site else ""
            )

        if using_cell_site_list:
            note = (
                "Cell tower/site latitude, cell tower/site longitude, and "
                "sector azimuth come only from the cell site list below; the "
                "disabled mappings above are not used."
            )
        required_text = ', '.join([
            *(self.application_field_label(field, data_type) for field in required),
            timestamp_requirement,
        ])
        self.mapping_note.setText(
            f"Required in original records: {required_text}. {note}"
        )
        self.update_cell_site_controls()
        self.update_preview_headers()

    def on_cell_site_enabled_changed(self):
        self.update_cell_site_controls()
        self.update_mapping_requirements()

    def cell_site_list_enabled(self):
        return (
            self.use_cell_site_list_checkbox.isChecked()
            and self.record_type_combo.currentData()
            in ('Tower/Sector', 'Distance from Tower')
        )

    def update_cell_site_controls(self):
        supported = self.record_type_combo.currentData() in (
            'Tower/Sector', 'Distance from Tower'
        )
        self.use_cell_site_list_checkbox.setEnabled(supported)
        self.use_cell_site_list_checkbox.setToolTip(
            "" if supported else
            "Separate cell site lists apply only to tower-based records."
        )
        controls_enabled = (
            supported
            and self.use_cell_site_list_checkbox.isChecked()
            and not self._cell_site_loading
        )
        self.cell_site_controls.setEnabled(controls_enabled)
        is_excel = bool(
            self.cell_site_path
            and Path(self.cell_site_path).suffix.lower() in ('.xls', '.xlsx')
        )
        self.cell_site_sheet_combo.setEnabled(
            controls_enabled and is_excel
        )

    def active_mapping_fields(self):
        """Return fields applicable to the selected record and timestamp layouts."""
        fields = set()
        if self.timestamp_layout_combo.currentData() == 'separate':
            fields.update({'Date', 'Time'})
        else:
            fields.add('Timestamp')

        data_type = self.record_type_combo.currentData()
        if data_type == 'Tower/Sector':
            if not self.cell_site_list_enabled():
                fields.update({'Latitude', 'Longitude', 'Azimuth'})
        elif data_type == 'Distance from Tower':
            fields.add('Distance')
            if not self.cell_site_list_enabled():
                fields.update({'Latitude', 'Longitude', 'Azimuth'})
        else:
            fields.update({'Latitude', 'Longitude', 'Accuracy'})
        return fields

    def update_timezone_controls(self):
        if not hasattr(self, 'filter_timezone_note'):
            return
        _, _, timezone_label, timezone_basis = (
            self.effective_filter_timezone_selection()
        )
        if timezone_basis == 'display':
            basis_text = "the selected display timezone"
        else:
            basis_text = "the source timezone because display is No Change"
        self.filter_timezone_note.setText(
            f"Filter dates and times use {timezone_label} ({basis_text}). "
            "Records are converted to UTC for comparison."
        )
        self.populate_filter_range_from_source()

    def update_filter_controls(self):
        enabled = self.filter_enabled_checkbox.isChecked()
        exact_times = enabled and self.filter_exact_times_checkbox.isChecked()
        self.filter_exact_times_checkbox.setEnabled(enabled)
        self.filter_start_edit.setEnabled(enabled)
        self.filter_end_edit.setEnabled(enabled)
        self.filter_preview_button.setEnabled(enabled)
        date_format = {
            'YMD': "yyyy-MM-dd",
            'YDM': "yyyy-dd-MM",
            'MDY': "MM/dd/yyyy",
            'DMY': "dd/MM/yyyy",
        }.get(self.date_order_combo.currentData(), "MM/dd/yyyy")
        display_format = f"{date_format} h:mm:ss AP" if exact_times else date_format
        start_datetime = self.filter_start_edit.dateTime()
        end_datetime = self.filter_end_edit.dateTime()
        start_block_state = self.filter_start_edit.blockSignals(True)
        end_block_state = self.filter_end_edit.blockSignals(True)
        self.filter_start_edit.setDisplayFormat(display_format)
        self.filter_end_edit.setDisplayFormat(display_format)
        self.filter_start_edit.setDateTime(start_datetime)
        self.filter_end_edit.setDateTime(end_datetime)
        self.filter_start_edit.blockSignals(start_block_state)
        self.filter_end_edit.blockSignals(end_block_state)
        if not enabled:
            self.filter_result_label.setText("Enable the filter to check how many rows will be retained.")

    def infer_source_date_order(self):
        """Infer a clear date order from the mapped timestamp or date column."""
        if self.source_dataframe is None:
            return None

        if self.timestamp_layout_combo.currentData() == 'separate':
            source_column = self.mapping_combos['Date'].currentData()
        else:
            source_column = self.mapping_combos['Timestamp'].currentData()
        if not source_column:
            return None

        inferred_orders = set()
        saw_year_first = False
        saw_year_last = False
        source_values = self.source_dataframe[source_column]
        for position in self.edge_sample_positions(len(source_values)):
            value = source_values.iloc[position]
            if pd.isna(value):
                continue
            if isinstance(value, (datetime, pd.Timestamp)):
                inferred_orders.add('YMD')
                saw_year_first = True
                continue

            match = re.search(
                r'(?<!\d)(\d{1,4})([-/.])(\d{1,2})\2(\d{1,4})(?!\d)',
                str(value),
            )
            if not match:
                continue

            first_text, separator, second_text, third_text = match.groups()
            first_value = int(first_text)
            second_value = int(second_text)
            third_value = int(third_text)
            if len(first_text) == 4:
                saw_year_first = True
                if separator == '.':
                    continue
                if second_value > 12 and third_value <= 12:
                    inferred_orders.add('YDM')
                elif third_value > 12 and second_value <= 12:
                    inferred_orders.add('YMD')
            else:
                saw_year_last = True
                if separator == '.' or (first_value > 12 and second_value <= 12):
                    inferred_orders.add('DMY')
                elif second_value > 12 and first_value <= 12:
                    inferred_orders.add('MDY')

        if saw_year_first and saw_year_last:
            return None
        if len(inferred_orders) == 1:
            return next(iter(inferred_orders))
        if not inferred_orders and saw_year_first:
            return 'YMD'
        return None

    @classmethod
    def edge_sample_positions(cls, row_count):
        """Return bounded positions from both ends of a source table."""
        head_stop = min(row_count, cls.TIMESTAMP_EDGE_SCAN_LIMIT)
        tail_start = max(head_stop, row_count - cls.TIMESTAMP_EDGE_SCAN_LIMIT)
        return [*range(head_stop), *range(tail_start, row_count)]

    def refresh_timestamp_defaults(self, *_args):
        """Refresh inferred date order and source timestamp filter boundaries."""
        if self._reloading_source:
            return
        inferred_order = self.infer_source_date_order()
        if inferred_order:
            inferred_index = self.date_order_combo.findData(inferred_order)
            previous_block_state = self.date_order_combo.blockSignals(True)
            self.date_order_combo.setCurrentIndex(inferred_index)
            self.date_order_combo.blockSignals(previous_block_state)
        self.update_filter_controls()
        self.populate_filter_range_from_source()

    def populate_filter_range_from_source(self, *_args):
        """Set filter endpoints to the earliest and latest parseable timestamps."""
        if self.source_dataframe is None:
            return

        mappings = self.current_mappings()
        timestamp_fields = (
            ('Date', 'Time')
            if self.timestamp_layout_combo.currentData() == 'separate'
            else ('Timestamp',)
        )
        if any(not mappings.get(field) for field in timestamp_fields):
            return

        timestamp_mappings = {
            field: mappings[field] for field in timestamp_fields
        }
        sample_positions = self.edge_sample_positions(len(self.source_dataframe))
        sampled_source = self.source_dataframe.iloc[sample_positions]
        normalized = self.build_normalized_dataframe(
            timestamp_mappings, sampled_source
        )
        source_timezone_name, source_offset_minutes = self.timezone_selection(
            self.source_timezone_combo
        )
        parser = KMLGenerator(self.source_path, self.record_type_combo.currentData(), {
            'source_utc_offset_minutes': source_offset_minutes,
            'source_timezone_name': source_timezone_name,
            'source_date_order': self.date_order_combo.currentData(),
        })
        def parse_first_valid(positions):
            for position in positions:
                row = normalized.iloc[position]
                try:
                    timestamp_value = parser.get_timestamp_value(row)
                    kml_timestamp, _ = parser.parse_timestamp_to_kml(
                        timestamp_value
                    )
                except TimestampResolutionError:
                    continue
                if kml_timestamp:
                    return datetime.strptime(
                        kml_timestamp, '%Y-%m-%dT%H:%M:%SZ'
                    ).replace(tzinfo=timezone.utc)
            return None

        scan_count = min(len(normalized), self.TIMESTAMP_EDGE_SCAN_LIMIT)
        first_timestamp = parse_first_valid(range(scan_count))
        last_timestamp = parse_first_valid(
            range(len(normalized) - 1, len(normalized) - scan_count - 1, -1)
        )
        parsed_timestamps = [
            timestamp for timestamp in (first_timestamp, last_timestamp)
            if timestamp is not None
        ]
        if not parsed_timestamps:
            return

        filter_timezone_name, filter_offset_minutes, _, _ = (
            self.effective_filter_timezone_selection()
        )
        if filter_timezone_name:
            filter_timezone = ZoneInfo(filter_timezone_name)
        else:
            filter_timezone = timezone(
                timedelta(minutes=filter_offset_minutes)
            )
        start_datetime = min(parsed_timestamps).astimezone(filter_timezone)
        end_datetime = max(parsed_timestamps).astimezone(filter_timezone)
        start_qdatetime = QDateTime.fromString(
            start_datetime.strftime('%Y-%m-%d %H:%M:%S'),
            'yyyy-MM-dd HH:mm:ss',
        )
        end_qdatetime = QDateTime.fromString(
            end_datetime.strftime('%Y-%m-%d %H:%M:%S'),
            'yyyy-MM-dd HH:mm:ss',
        )
        start_block_state = self.filter_start_edit.blockSignals(True)
        end_block_state = self.filter_end_edit.blockSignals(True)
        self.filter_start_edit.setDateTime(start_qdatetime)
        self.filter_end_edit.setDateTime(end_qdatetime)
        self.filter_start_edit.blockSignals(start_block_state)
        self.filter_end_edit.blockSignals(end_block_state)

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
        date_format = {
            'YMD': "yyyy-MM-dd",
            'YDM': "yyyy-dd-MM",
            'MDY': "MM-dd-yyyy",
            'DMY': "dd-MM-yyyy",
        }.get(self.date_order_combo.currentData(), "MM-dd-yyyy")
        return (
            start_datetime.toString(f"{date_format} HH:mm:ss"),
            end_datetime.toString(f"{date_format} HH:mm:ss"),
        )

    def current_mappings(self):
        """Return mappings that are active for the selected import layouts."""
        active_fields = self.active_mapping_fields()
        return {
            field: combo.currentData()
            for field, combo in self.mapping_combos.items()
            if field in active_fields
        }

    def current_original_key_mappings(self):
        return {
            field: combo.currentData()
            for field, combo in self.original_key_mapping_combos.items()
        }

    def current_cell_site_mappings(self):
        return {
            field: combo.currentData()
            for field, combo in self.cell_site_mapping_combos.items()
        }

    def validate_cell_site_configuration(self):
        """Return complete CSL mappings or raise a user-facing validation error."""
        if self.cell_site_dataframe is None or not self.cell_site_path:
            raise ValueError("Select a cell site list file before importing.")

        original_key_mappings = self.current_original_key_mappings()
        cell_site_mappings = self.current_cell_site_mappings()
        missing = []
        for field in ('Site ID', 'Sector ID'):
            if not original_key_mappings.get(field):
                missing.append(f"Original records: {self.CELL_SITE_FIELD_LABELS[field]}")
        for field in ('Site ID', 'Sector ID', 'Latitude', 'Longitude'):
            if not cell_site_mappings.get(field):
                missing.append(f"Cell site list: {self.CELL_SITE_FIELD_LABELS[field]}")
        if missing:
            raise ValueError(
                "Map the following required cell site fields:\n\n"
                + "\n".join(missing)
            )

        for source_name, mappings in (
            ('original records join', original_key_mappings),
            ('cell site list', cell_site_mappings),
        ):
            selected_columns = [
                column for column in mappings.values() if column
            ]
            if len(selected_columns) != len(set(selected_columns)):
                raise ValueError(
                    f"Each {source_name} column can be assigned to only one "
                    "cell site mapping role."
                )
        return original_key_mappings, cell_site_mappings

    def apply_cell_site_list(self, normalized, source_dataframe=None):
        """Resolve optional CSL fields and return metadata suitable for the log."""
        self.reference_sites_dataframe = None
        if not self.cell_site_list_enabled():
            return normalized, {'enabled': False}

        source_dataframe = (
            self.source_dataframe
            if source_dataframe is None
            else source_dataframe
        )
        original_key_mappings, cell_site_mappings = (
            self.validate_cell_site_configuration()
        )
        self.reference_sites_dataframe = self.build_reference_site_dataframe(
            self.cell_site_dataframe,
            cell_site_mappings,
            self.cell_site_header_row_spinbox.value(),
        )
        policy = self.cell_site_policy_combo.currentData()
        resolved, resolution_metadata = self.resolve_cell_site_fields(
            normalized,
            source_dataframe,
            self.cell_site_dataframe,
            original_key_mappings,
            cell_site_mappings,
            policy,
            self.cell_site_header_row_spinbox.value(),
        )
        is_excel = Path(self.cell_site_path).suffix.lower() in ('.xls', '.xlsx')
        metadata = {
            'enabled': True,
            'file_path': str(self.cell_site_path),
            'file_name': Path(self.cell_site_path).name,
            'worksheet': (
                self.cell_site_sheet_combo.currentText() if is_excel else None
            ),
            'header_row': self.cell_site_header_row_spinbox.value(),
            'original_key_mappings': dict(original_key_mappings),
            'cell_site_mappings': {
                field: column for field, column in cell_site_mappings.items()
                if column
            },
            'policy': policy,
            'policy_label': self.cell_site_policy_combo.currentText(),
            **resolution_metadata,
        }
        source_header_row = self.header_row_spinbox.value()
        metadata['unmatched_source_rows'] = [
            position + source_header_row
            for position in metadata.pop('unmatched_row_positions')
        ]
        metadata['missing_key_source_rows'] = [
            position + source_header_row
            for position in metadata.pop('missing_key_row_positions')
        ]
        metadata['source_row_audit_limit'] = self.CELL_SITE_ROW_AUDIT_LIMIT
        return resolved, metadata

    @classmethod
    def build_reference_site_dataframe(
        cls, cell_site_dataframe, mappings, cell_site_header_row=1
    ):
        """Keep complete CSL keys with one unambiguous mapped location."""
        groups = {}
        for position, (_, row) in enumerate(cell_site_dataframe.iterrows()):
            key = tuple(
                cls.normalize_lookup_value(row[mappings[field]])
                for field in ('Site ID', 'Sector ID')
            )
            if any(value is None for value in key):
                continue
            groups.setdefault(key, []).append((position, row))

        reference_rows = []
        for entries in groups.values():
            coordinate_signatures = {
                tuple(
                    cls.normalize_mapped_tower_value(row[mappings[field]])
                    for field in ('Latitude', 'Longitude')
                )
                for _position, row in entries
            }
            if len(coordinate_signatures) != 1:
                continue
            first_row = entries[0][1]
            reference_rows.append({
                field: first_row[mappings[field]]
                for field in ('Site ID', 'Latitude', 'Longitude')
            } | {
                'CSL Source Rows': tuple(
                    position + max(int(cell_site_header_row), 1) + 1
                    for position, _row in entries
                )
            })

        return pd.DataFrame(
            reference_rows,
            columns=('Site ID', 'Latitude', 'Longitude', 'CSL Source Rows'),
        )

    def build_normalized_dataframe(self, mappings, source_dataframe=None):
        """Build the in-memory application columns from source mappings."""
        source_dataframe = (
            self.source_dataframe
            if source_dataframe is None
            else source_dataframe
        )
        normalized = pd.DataFrame(index=source_dataframe.index)
        for field, source_column in mappings.items():
            if source_column:
                target_field = field
                if field == 'Time' and 'utc' in self.normalize_name(source_column).split():
                    target_field = 'Time (UTC)'
                normalized[target_field] = source_dataframe[source_column]

        timestamp_source = mappings.get('Timestamp')
        if timestamp_source and 'utc' in self.normalize_name(timestamp_source).split():
            normalized['Timestamp'] = normalized['Timestamp'].map(
                lambda value: value if pd.isna(value) else f"{value} UTC"
            )
        return normalized

    @staticmethod
    def normalize_lookup_value(value):
        """Normalize one site/sector identifier without exposing it in logs."""
        if pd.isna(value):
            return None
        text = str(value).strip()
        if not text:
            return None
        if re.fullmatch(r'[+-]?\d+\.0+', text):
            text = text.split('.', 1)[0]
        return text.casefold()

    @staticmethod
    def normalize_mapped_tower_value(value):
        """Normalize mapped CSL values for duplicate comparison."""
        if pd.isna(value):
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            number = float(text)
        except (TypeError, ValueError):
            return ('text', text.casefold())
        if not math.isfinite(number):
            return ('text', text.casefold())
        return ('number', number)

    @staticmethod
    def display_cell_site_value(value):
        if pd.isna(value) or not str(value).strip():
            return '<blank>'
        text = str(value).strip()
        if re.fullmatch(r'[+-]?\d+\.0+', text):
            return text.split('.', 1)[0]
        return text

    @classmethod
    def resolve_cell_site_fields(
        cls,
        normalized,
        source_dataframe,
        cell_site_dataframe,
        original_key_mappings,
        cell_site_mappings,
        policy,
        cell_site_header_row=1,
    ):
        """Resolve tower coordinates and azimuth through a two-column CSL key."""
        supported_policies = {
            'cell_site_first_fallback_original',
            'cell_site_only',
            'original_first_fallback_cell_site',
        }
        if policy not in supported_policies:
            raise ValueError(f"Unknown cell site resolution policy: {policy}")

        def lookup_key(row, mappings):
            return tuple(
                cls.normalize_lookup_value(row[mappings[field]])
                for field in ('Site ID', 'Sector ID')
            )

        referenced_keys = set()
        for _, source_row in source_dataframe.iterrows():
            key = lookup_key(source_row, original_key_mappings)
            if all(value is not None for value in key):
                referenced_keys.add(key)

        cell_site_groups = {}
        ignored_missing_key_rows = 0
        for position, (_, cell_site_row) in enumerate(
            cell_site_dataframe.iterrows()
        ):
            key = lookup_key(cell_site_row, cell_site_mappings)
            if any(value is None for value in key):
                ignored_missing_key_rows += 1
                continue
            cell_site_groups.setdefault(key, []).append(
                (position, cell_site_row)
            )

        fields = ('Latitude', 'Longitude', 'Azimuth')
        mapped_fields = tuple(
            field for field in fields if cell_site_mappings.get(field)
        )
        cell_site_rows = {}
        duplicate_keys_collapsed = 0
        duplicate_rows_collapsed = 0
        unreferenced_conflicting_keys_ignored = 0
        conflicting_used_keys = []
        for key, entries in cell_site_groups.items():
            cell_site_rows[key] = entries[0][1]
            if len(entries) == 1:
                continue

            signatures = {
                tuple(
                    cls.normalize_mapped_tower_value(
                        row[cell_site_mappings[field]]
                    )
                    for field in mapped_fields
                )
                for _, row in entries
            }
            if len(signatures) == 1:
                duplicate_keys_collapsed += 1
                duplicate_rows_collapsed += len(entries) - 1
                continue
            if key not in referenced_keys:
                unreferenced_conflicting_keys_ignored += 1
                continue

            differing_fields = []
            for field in mapped_fields:
                column = cell_site_mappings[field]
                values = {
                    cls.normalize_mapped_tower_value(row[column])
                    for _, row in entries
                }
                if len(values) > 1:
                    differing_fields.append(field)
            conflicting_used_keys.append((key, entries, differing_fields))

        if conflicting_used_keys:
            conflict_count = len(conflicting_used_keys)
            details = []
            for _key, entries, differing_fields in conflicting_used_keys[
                :cls.CELL_SITE_CONFLICT_DISPLAY_LIMIT
            ]:
                first_row = entries[0][1]
                site_id = cls.display_cell_site_value(
                    first_row[cell_site_mappings['Site ID']]
                )
                sector_id = cls.display_cell_site_value(
                    first_row[cell_site_mappings['Sector ID']]
                )
                row_numbers = ', '.join(
                    str(position + cell_site_header_row + 1)
                    for position, _row in entries
                )
                field_details = []
                for field in differing_fields:
                    column = cell_site_mappings[field]
                    display_values = []
                    normalized_values = set()
                    for _position, row in entries:
                        normalized_value = cls.normalize_mapped_tower_value(
                            row[column]
                        )
                        if normalized_value in normalized_values:
                            continue
                        normalized_values.add(normalized_value)
                        display_values.append(
                            cls.display_cell_site_value(row[column])
                        )
                    field_details.append(
                        f"{cls.CELL_SITE_FIELD_LABELS[field]}: "
                        + ' vs '.join(display_values)
                    )
                details.append(
                    f"- Site / Node ID {site_id}; Sector / Cell ID "
                    f"{sector_id}; cell site rows {row_numbers}; "
                    + '; '.join(field_details)
                )
            omitted_count = (
                conflict_count - cls.CELL_SITE_CONFLICT_DISPLAY_LIMIT
            )
            if omitted_count > 0:
                details.append(f"- ...and {omitted_count} more conflicting keys")
            raise ValueError(
                "The cell site list contains conflicting tower data for "
                f"{conflict_count} mapped site/sector "
                f"{'key' if conflict_count == 1 else 'keys'} used by the "
                "original records:\n\n"
                + '\n'.join(details)
                + "\n\nCorrect or remove the conflicting cell site rows, then "
                "import again. Identical mapped duplicates are accepted "
                "automatically."
            )

        resolved = normalized.copy()
        for field in fields:
            if field not in resolved:
                resolved[field] = pd.NA

        metadata = {
            'input_rows': len(source_dataframe),
            'cell_site_rows': len(cell_site_dataframe),
            'cell_site_rows_ignored_missing_key': ignored_missing_key_rows,
            'duplicate_keys_collapsed': duplicate_keys_collapsed,
            'duplicate_rows_collapsed': duplicate_rows_collapsed,
            'unreferenced_conflicting_keys_ignored': (
                unreferenced_conflicting_keys_ignored
            ),
            'matched_rows': 0,
            'unmatched_rows': 0,
            'missing_key_rows': 0,
            'unmatched_row_positions': [],
            'missing_key_row_positions': [],
            'fields_from_cell_site_list': {field: 0 for field in fields},
            'fields_from_original_records': {field: 0 for field in fields},
            'fields_left_missing': {field: 0 for field in fields},
        }

        for position in range(len(source_dataframe)):
            source_row = source_dataframe.iloc[position]
            output_index = resolved.index[position]
            key = lookup_key(source_row, original_key_mappings)
            if any(value is None for value in key):
                metadata['missing_key_rows'] += 1
                if len(metadata['missing_key_row_positions']) < cls.CELL_SITE_ROW_AUDIT_LIMIT:
                    metadata['missing_key_row_positions'].append(position + 1)
                cell_site_row = None
            else:
                cell_site_row = cell_site_rows.get(key)
                if cell_site_row is None:
                    metadata['unmatched_rows'] += 1
                    if len(metadata['unmatched_row_positions']) < cls.CELL_SITE_ROW_AUDIT_LIMIT:
                        metadata['unmatched_row_positions'].append(position + 1)
                else:
                    metadata['matched_rows'] += 1

            for field in fields:
                original_value = resolved.at[output_index, field]
                cell_site_column = cell_site_mappings.get(field)
                cell_site_value = (
                    pd.NA
                    if cell_site_row is None or not cell_site_column
                    else cell_site_row[cell_site_column]
                )
                original_available = not pd.isna(original_value) and str(original_value).strip()
                cell_site_available = not pd.isna(cell_site_value) and str(cell_site_value).strip()

                if policy == 'cell_site_only':
                    candidates = (('cell_site_list', cell_site_value, cell_site_available),)
                elif policy == 'original_first_fallback_cell_site':
                    candidates = (
                        ('original_records', original_value, original_available),
                        ('cell_site_list', cell_site_value, cell_site_available),
                    )
                else:
                    candidates = (
                        ('cell_site_list', cell_site_value, cell_site_available),
                        ('original_records', original_value, original_available),
                    )

                selected_source = None
                selected_value = pd.NA
                for candidate_source, candidate_value, available in candidates:
                    if available:
                        selected_source = candidate_source
                        selected_value = candidate_value
                        break
                resolved.at[output_index, field] = selected_value
                if selected_source == 'cell_site_list':
                    metadata['fields_from_cell_site_list'][field] += 1
                elif selected_source == 'original_records':
                    metadata['fields_from_original_records'][field] += 1
                else:
                    metadata['fields_left_missing'][field] += 1

        return resolved, metadata

    def preview_filter_results(self):
        """Show timestamp and coordinate counts before accepting the import."""
        if self.source_dataframe is None:
            QMessageBox.warning(self, "No Records", "Select a source file before checking the filter.")
            return
        mappings = self.current_mappings()
        timestamp_fields = ('Date', 'Time') if self.timestamp_layout_combo.currentData() == 'separate' else ('Timestamp',)
        coordinate_fields = (
            () if self.cell_site_list_enabled() else ('Latitude', 'Longitude')
        )
        required_fields = (*coordinate_fields, *timestamp_fields)
        missing_fields = [
            field for field in required_fields if not mappings.get(field)
        ]
        if missing_fields:
            missing_labels = [
                self.application_field_label(field) for field in missing_fields
            ]
            QMessageBox.warning(
                self,
                "Incomplete Mapping",
                "Map the following fields before checking the filter:\n\n"
                + ", ".join(missing_labels),
            )
            return

        normalized = self.build_normalized_dataframe(mappings)
        try:
            normalized, _ = self.apply_cell_site_list(normalized)
            _, metadata = self.apply_datetime_filter(normalized)
        except ValueError as error:
            QMessageBox.warning(self, "Import Validation", str(error))
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

        source_settings = {
            'source_utc_offset_minutes': self.timezone_selection(self.source_timezone_combo)[1],
            'source_timezone_name': self.timezone_selection(self.source_timezone_combo)[0],
            'source_date_order': self.date_order_combo.currentData(),
        }
        record_parser = KMLGenerator(
            self.source_path, self.record_type_combo.currentData(),
            source_settings
        )
        (
            filter_timezone_name,
            filter_offset_minutes,
            filter_timezone_label,
            filter_timezone_basis,
        ) = self.effective_filter_timezone_selection()
        boundary_parser = KMLGenerator(
            self.source_path,
            self.record_type_combo.currentData(),
            {
                'source_utc_offset_minutes': filter_offset_minutes,
                'source_timezone_name': filter_timezone_name,
                'source_date_order': self.date_order_combo.currentData(),
            },
        )
        start_local, end_local = self.current_filter_boundaries()

        try:
            start_kml, _ = boundary_parser.parse_timestamp_to_kml(start_local)
            end_kml, _ = boundary_parser.parse_timestamp_to_kml(end_local)
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
                timestamp = record_parser.get_timestamp_value(row)
                record_kml, _ = record_parser.parse_timestamp_to_kml(timestamp)
            except TimestampResolutionError:
                record_kml = None
            if not record_kml:
                unparseable_count += 1
            elif start_kml <= record_kml <= end_kml:
                retained_indexes.append(row_index)

        filtered = normalized.loc[retained_indexes].copy()
        valid_coordinate_rows = sum(
            record_parser.get_valid_coordinates(row) is not None
            for _, row in filtered.iterrows()
        )
        metadata = {
            'enabled': True,
            'exact_times': self.filter_exact_times_checkbox.isChecked(),
            'filter_timezone_label': filter_timezone_label,
            'filter_timezone_basis': filter_timezone_basis,
            'start_local': start_local,
            'end_local': end_local,
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
        required = (
            [] if self.cell_site_list_enabled() else ['Latitude', 'Longitude']
        )
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
            normalized, cell_site_metadata = self.apply_cell_site_list(
                normalized
            )
        except ValueError as error:
            QMessageBox.warning(self, "Cell Site List Mapping", str(error))
            return

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
        self.selected_cell_site_metadata = cell_site_metadata
        self.selected_sheet_name = (
            self.sheet_combo.currentText() if self.sheet_combo.isEnabled() else None
        )
        self.selected_header_row = self.header_row_spinbox.value()
        if cell_site_metadata.get('enabled'):
            self.selected_cell_site_sheet_name = cell_site_metadata['worksheet']
            self.selected_cell_site_header_row = cell_site_metadata['header_row']
        self.accept()