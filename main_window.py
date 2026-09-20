"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import hashlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, numbers
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGridLayout, QPushButton, QLabel, QFileDialog, 
                             QSpinBox, QDoubleSpinBox, QRadioButton, QButtonGroup, 
                             QTextEdit, QGroupBox, QColorDialog, QProgressBar, 
                             QMessageBox, QTabWidget, QCheckBox, QMenu, QComboBox, QLineEdit, QFrame, QScrollArea)
from PyQt6.QtCore import Qt, QSettings, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap, QPainter, QPen

from dialogs import DisclaimerDialog
from geolibre_launcher import GeoLibreLaunchWorker
from import_wizard import (
    FIXED_UTC_OFFSETS,
    NAMED_TIMEZONE_CHOICES,
    ImportWizardDialog,
    SourceFileLoadWorker,
    fixed_offset_label,
    timezone_choice_data,
)
from widgets import DragDropWidget
from kml_generator import KMLGenerator
from version import APP_VERSION


class MainWindow(QMainWindow):
    file_inspection_finished = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Open Source Location Data Visualizer")
        self.setGeometry(100, 100, 600, 800)  # Increased height to give Settings pane more space
        
        # Set custom window icon
        self.setWindowIcon(self.create_pushpin_icon())
        
        # Initialize variables
        self.data_file = None
        self.imported_dataframe = None
        self.import_metadata = None
        self.import_target_timezone_name = None
        self.import_target_offset_minutes = None
        self.kml_generator = None
        self.generation_messages = []
        self.current_generation_settings = {}
        self.current_generation_type = None
        self.current_generation_source_file = None
        self.current_import_metadata = None
        self.generation_started_utc = None
        self.open_viewer_after_generation = False
        self.viewer_launcher = None
        self.pending_viewer_geojson_path = None
        self.restore_generation_actions_after_viewer = False
        self.file_inspector = None
        self.pending_inspection_path = None
        self.settings = QSettings("OpenSource", "LocationDataVisualizer")
        
        # Set up UI
        self.setup_ui()
        self.apply_dark_theme()
        
        # Show disclaimer dialog on startup
        self.show_disclaimer_dialog()
        
        # Add welcome message
        self.add_status_message("Drag and drop a CSV or Excel file, or click 'Browse for File', to get started.")
        self.add_status_message("Click 'Import Original Records' to open the column-mapping wizard.")
        self.add_status_message("Default templates (available in the Green menu button above) are detected automatically; other files open the column-mapping wizard.")
        self.add_status_message("Adjust settings and colors, then save outputs or save and open them in the included viewer.")
        self.add_status_message("Each generation includes same-named KML, GeoJSON, and TXT files.")


    
    def show_disclaimer_dialog(self):
        """Show the disclaimer dialog"""
        dialog = DisclaimerDialog(self)
        dialog.exec()
    
    def handle_footer_link(self, link):
        """Handle clicks on footer links"""
        if link == "license://show":
            # Show the license dialog
            from license_dialog import LicenseDialog
            self.license_window = LicenseDialog(self)
            self.license_window.show()
        elif link.startswith("http://") or link.startswith("https://"):
            # Open GitHub link in browser
            import webbrowser
            webbrowser.open(link)
        
    def setup_ui(self):
        """Set up the user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 5)
        layout.setSpacing(8)  # Control spacing between main sections
        
        # Header section with title and info button
        header_layout = QHBoxLayout()
        
        # Header title
        header_label = QLabel("Open Source Location Data Visualizer")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_font = QFont()
        header_font.setPointSize(16)
        header_font.setBold(True)
        header_label.setFont(header_font)
        
        # Templates button
        self.template_button = QPushButton("📁 Templates")
        self.template_button.setMaximumWidth(120)
        self.template_button.setToolTip("Download template Excel files with correct headers for each data type")
        self.template_button.clicked.connect(self.show_template_menu)
        self.template_button.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 4px;
                border: none;
                margin-right: 8px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:pressed {
                background-color: #1e7e34;
            }
        """)
        
        # Info button
        self.info_button = QPushButton("ℹ️ Info")
        self.info_button.setMaximumWidth(100)
        self.info_button.setToolTip("Show important information and disclaimers")
        self.info_button.clicked.connect(self.show_disclaimer_dialog)
        self.info_button.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        
        header_layout.addStretch()
        header_layout.addWidget(header_label)
        header_layout.addStretch()
        header_layout.addWidget(self.template_button)
        header_layout.addWidget(self.info_button)
        
        layout.addLayout(header_layout, 0)  # No stretch for header
        
        # File input section
        file_group = QGroupBox("Input Data")
        file_group.setStyleSheet("""
            QGroupBox { 
                border: 2px solid #555555; 
                border-radius: 8px; 
                font-weight: bold; 
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        file_layout = QVBoxLayout(file_group)
        
        # Create drag-and-drop widget
        self.drag_drop_widget = DragDropWidget()
        self.drag_drop_widget.file_dropped.connect(self.handle_file_dropped)
        self.drag_drop_widget.browse_button.clicked.connect(self.select_file)
        file_layout.addWidget(self.drag_drop_widget)
        
        # File status layout
        file_status_layout = QHBoxLayout()
        self.file_status_label = QLabel("Status:")
        self.file_label = QLabel("No file selected")
        self.file_label.setStyleSheet("color: #888888; font-style: italic;")
        
        file_status_layout.addWidget(self.file_status_label)
        file_status_layout.addWidget(self.file_label, 1)
        file_layout.addLayout(file_status_layout)
        
        layout.addWidget(file_group, 0)  # No stretch for file input
        
        # Settings tabs
        tab_widget = QTabWidget()
        
        # Data Type Tab
        data_type_tab = QWidget()
        data_type_layout = QVBoxLayout(data_type_tab)
        
        # Add label
        detection_label = QLabel("Data type will be automatically detected from input file column headers:")
        detection_label.setStyleSheet("color: #888888; font-style: italic; margin-bottom: 10px;")
        data_type_layout.addWidget(detection_label)
        
        self.data_type_group = QButtonGroup()
        self.tower_radio = QRadioButton("Tower/Sector Data")
        self.ta_radio = QRadioButton("Distance from Tower Data")
        self.gps_radio = QRadioButton("Location Point Data")
        
        # Make radio buttons (read-only display)
        self.tower_radio.setEnabled(False)
        self.ta_radio.setEnabled(False)
        self.gps_radio.setEnabled(False)
        
        # Start with none selected - will be set when file is validated      
        self.data_type_group.addButton(self.tower_radio)
        self.data_type_group.addButton(self.ta_radio)
        self.data_type_group.addButton(self.gps_radio)
        
        data_type_layout.addWidget(self.tower_radio)
        data_type_layout.addWidget(self.ta_radio)
        data_type_layout.addWidget(self.gps_radio)
        
        # Add custom label field
        label_layout = QVBoxLayout()
        label_layout.setContentsMargins(20, 15, 0, 0)  # Indent and add top margin
        
        custom_label_desc = QLabel("Record Name or Description (optional):")
        custom_label_desc.setStyleSheet("color: #ffffff; font-style: normal; font-size: 12px;")
        label_layout.addWidget(custom_label_desc)
        
        self.custom_label_input = QLineEdit()
        self.custom_label_input.setPlaceholderText("e.g., 'T-Mobile Timing Advance - 555-1234'")
        self.custom_label_input.setMaximumWidth(300)
        self.custom_label_input.setStyleSheet("""
            QLineEdit {
                padding: 6px;
                border: 1px solid #555555;
                border-radius: 4px;
                background-color: #1e1e1e;
                color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #0078d4;
            }
        """)
        label_layout.addWidget(self.custom_label_input)
        
        data_type_layout.addLayout(label_layout)
        data_type_layout.addStretch()
        
        tab_widget.addTab(data_type_tab, "Data Type")
        
        # Visualization Settings Tab
        viz_tab = QWidget()
        viz_layout = QGridLayout(viz_tab)
        viz_layout.setVerticalSpacing(8)  # Compact spacing for Settings controls
        
        row = 0
        
        # ============ TOWER/SECTOR SETTINGS ============
        tower_label = QLabel("Tower/Sector Settings")
        tower_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tower_label.setStyleSheet("color: #4ecdc4; font-weight: bold; font-size: 14px;")
        viz_layout.addWidget(tower_label, row, 0, 1, 2)
        row += 1
        
        # Leg length
        leg_length_label = QLabel("Tower/Sector Leg Length (miles):")
        leg_length_label.setToolTip("Length of the lines extending from the tower")
        viz_layout.addWidget(leg_length_label, row, 0)
        self.leg_length_spinbox = QDoubleSpinBox()
        self.leg_length_spinbox.setRange(0.5, 20.0)
        self.leg_length_spinbox.setValue(3.0)
        self.leg_length_spinbox.setSingleStep(0.5)
        viz_layout.addWidget(self.leg_length_spinbox, row, 1)
        row += 1
        
        # Shaded area length
        shaded_area_label = QLabel("Tower/Sector Shaded Area Length (miles):")
        shaded_area_label.setToolTip("Length of the shaded wedge (can be shorter or equal to leg length)")
        viz_layout.addWidget(shaded_area_label, row, 0)
        self.shaded_area_spinbox = QDoubleSpinBox()
        self.shaded_area_spinbox.setRange(0.1, 10.0)
        self.shaded_area_spinbox.setValue(1.0)
        self.shaded_area_spinbox.setSingleStep(0.1)
        viz_layout.addWidget(self.shaded_area_spinbox, row, 1)
        row += 1
        
        # Shaded area azimuth and width
        azimuth_label = QLabel("Tower/Sector Width (degrees):")
        azimuth_label.setToolTip("Angular width of the tower sector shaded area")
        viz_layout.addWidget(azimuth_label, row, 0)
        self.azimuth_spinbox = QSpinBox()
        self.azimuth_spinbox.setRange(30, 360)
        self.azimuth_spinbox.setValue(120)
        viz_layout.addWidget(self.azimuth_spinbox, row, 1)
        row += 1
        
        # Separator
        separator1 = QFrame()
        separator1.setFrameShape(QFrame.Shape.HLine)
        separator1.setFrameShadow(QFrame.Shadow.Sunken)
        separator1.setStyleSheet("color: #333333;")
        viz_layout.addWidget(separator1, row, 0, 1, 2)
        row += 1
        
        # ============ DISTANCE FROM TOWER SETTINGS ============
        ta_label = QLabel("Distance from Tower Settings")
        ta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ta_label.setStyleSheet("color: #4ecdc4; font-weight: bold; font-size: 14px;")
        viz_layout.addWidget(ta_label, row, 0, 1, 2)
        row += 1
        
        # Distance from Tower units dropdown
        ta_distance_units_label = QLabel("Distance from Tower Units:")
        ta_distance_units_label.setToolTip("Select the units used for distance from tower in your data")
        viz_layout.addWidget(ta_distance_units_label, row, 0)
        self.ta_distance_units_combo = QComboBox()
        self.ta_distance_units_combo.addItems(["Meters", "Feet", "Miles", "Kilometers"])
        self.ta_distance_units_combo.setCurrentText("Miles")  # Default to miles for distance from tower
        viz_layout.addWidget(self.ta_distance_units_combo, row, 1)
        row += 1
        
        # Inside Band Distance (before distance - extends inward from distance point)
        inside_band_label = QLabel("Band Distance Before (Inner):")
        inside_band_label.setToolTip("Distance extending inward from the distance value (creates band from distance - this value to distance)")
        viz_layout.addWidget(inside_band_label, row, 0)
        self.inside_band_spinbox = QDoubleSpinBox()
        self.inside_band_spinbox.setRange(0.0, 10000.0)
        self.inside_band_spinbox.setValue(0.0)  # Default 0 (no inner band)
        self.inside_band_spinbox.setSingleStep(1.0)
        viz_layout.addWidget(self.inside_band_spinbox, row, 1)
        row += 1
        
        # Outside Band Distance (after distance - extends outward from distance point)
        outside_band_label = QLabel("Band Distance After (Outer):")
        outside_band_label.setToolTip("Distance extending outward from the distance value (creates band from distance to distance + this value)")
        viz_layout.addWidget(outside_band_label, row, 0)
        self.band_thickness_spinbox = QDoubleSpinBox()
        self.band_thickness_spinbox.setRange(0.0, 10000.0)
        self.band_thickness_spinbox.setValue(0.0)  # Default 0 meters
        self.band_thickness_spinbox.setSingleStep(1.0)
        viz_layout.addWidget(self.band_thickness_spinbox, row, 1)
        row += 1
        
        # Band Distance Units dropdown
        band_units_label = QLabel("Band Distance Units:")
        band_units_label.setToolTip("Units for both inner and outer band distances")
        viz_layout.addWidget(band_units_label, row, 0)
        self.band_thickness_units_combo = QComboBox()
        self.band_thickness_units_combo.addItems(["Meters", "Miles"])
        self.band_thickness_units_combo.setCurrentText("Meters")  # Default to meters
        viz_layout.addWidget(self.band_thickness_units_combo, row, 1)
        row += 1
        
        # Separator
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setFrameShadow(QFrame.Shadow.Sunken)
        separator2.setStyleSheet("color: #333333;")
        viz_layout.addWidget(separator2, row, 0, 1, 2)
        row += 1
        
        # ============ LOCATION POINT SETTINGS ============
        gps_label = QLabel("Location Point Settings")
        gps_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        gps_label.setStyleSheet("color: #4ecdc4; font-weight: bold; font-size: 14px;")
        viz_layout.addWidget(gps_label, row, 0, 1, 2)
        row += 1
        
        # Location Point accuracy units dropdown
        gps_units_label = QLabel("Location Point Accuracy Units:")
        gps_units_label.setToolTip("Select the units used for location point accuracy in your data")
        viz_layout.addWidget(gps_units_label, row, 0)
        self.gps_units_combo = QComboBox()
        self.gps_units_combo.addItems(["Meters", "Feet", "Miles", "Kilometers"])
        self.gps_units_combo.setCurrentText("Meters")  # Default to meters
        viz_layout.addWidget(self.gps_units_combo, row, 1)
        row += 1
        
        # Default Location Point accuracy for missing data
        default_accuracy_label = QLabel("Default Location Accuracy:")
        default_accuracy_label.setToolTip("Default accuracy radius used when input location point data has no accuracy value (uses Location Point Accuracy Units above)")
        viz_layout.addWidget(default_accuracy_label, row, 0)
        self.default_accuracy_spinbox = QSpinBox()
        self.default_accuracy_spinbox.setRange(1, 10000)
        self.default_accuracy_spinbox.setValue(100)  # Default 100
        viz_layout.addWidget(self.default_accuracy_spinbox, row, 1)
        row += 1
        
        # Separator
        separator3 = QFrame()
        separator3.setFrameShape(QFrame.Shape.HLine)
        separator3.setFrameShadow(QFrame.Shadow.Sunken)
        separator3.setStyleSheet("color: #333333;")
        viz_layout.addWidget(separator3, row, 0, 1, 2)
        row += 1
        
        # ============ TIMELINE SETTINGS ============
        timeline_label = QLabel("Timeline Settings")
        timeline_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timeline_label.setStyleSheet("color: #4ecdc4; font-weight: bold; font-size: 14px;")
        viz_layout.addWidget(timeline_label, row, 0, 1, 2)
        row += 1
        
        # Duration setting for time animation
        duration_label = QLabel("Animation Duration (minutes):")
        duration_label.setToolTip("How long each visualization stays visible during time animation (end time = start time + duration)")
        viz_layout.addWidget(duration_label, row, 0)
        self.duration_spinbox = QSpinBox()
        self.duration_spinbox.setRange(1, 1440)  # 1 minute to 24 hours
        self.duration_spinbox.setValue(30)  # Default to 30 minutes
        viz_layout.addWidget(self.duration_spinbox, row, 1)
        row += 1

        source_timezone_label = QLabel("Source timestamps are in:")
        source_timezone_label.setToolTip(
            "Custom imports copy the source interpretation selected in Import Records. "
            "This value is used when generating output."
        )
        viz_layout.addWidget(source_timezone_label, row, 0)
        self.source_timezone_combo = QComboBox()
        for label, timezone_name in NAMED_TIMEZONE_CHOICES:
            self.source_timezone_combo.addItem(
                label, timezone_choice_data(timezone_name=timezone_name)
            )
        for offset_minutes in FIXED_UTC_OFFSETS:
            self.source_timezone_combo.addItem(
                fixed_offset_label(offset_minutes),
                timezone_choice_data(fixed_offset_minutes=offset_minutes),
            )
        self.set_source_timestamp_selection(None, 0)
        viz_layout.addWidget(self.source_timezone_combo, row, 1)
        row += 1

        target_timezone_label = QLabel("Display timestamps as:")
        target_timezone_label.setToolTip(
            "Custom imports copy the display timezone selected in Import Records. "
            "No Change preserves the source timezone in output labels."
        )
        viz_layout.addWidget(target_timezone_label, row, 0)
        self.target_timezone_combo = QComboBox()
        self.target_timezone_combo.addItem(
            "No Change", timezone_choice_data(no_change=True)
        )
        for label, timezone_name in NAMED_TIMEZONE_CHOICES:
            self.target_timezone_combo.addItem(
                label, timezone_choice_data(timezone_name=timezone_name)
            )
        for offset_minutes in FIXED_UTC_OFFSETS:
            self.target_timezone_combo.addItem(
                fixed_offset_label(offset_minutes),
                timezone_choice_data(fixed_offset_minutes=offset_minutes),
            )
        self.target_timezone_combo.currentIndexChanged.connect(
            self.update_target_timestamp_selection
        )
        viz_layout.addWidget(self.target_timezone_combo, row, 1)
        row += 1

        date_order_label = QLabel("Date format in source records:")
        date_order_label.setToolTip(
            "Match the date order used in source timestamps; dash and slash separators are supported"
        )
        viz_layout.addWidget(date_order_label, row, 0)
        self.source_date_order_combo = QComboBox()
        self.source_date_order_combo.addItem("Year-Month-Day (YYYY-MM-DD or YYYY/MM/DD)", "YMD")
        self.source_date_order_combo.addItem("Year-Day-Month (YYYY-DD-MM or YYYY/DD/MM)", "YDM")
        self.source_date_order_combo.addItem("Month-Day-Year (MM-DD-YYYY or MM/DD/YYYY)", "MDY")
        self.source_date_order_combo.addItem("Day-Month-Year (DD-MM-YYYY or DD/MM/YYYY)", "DMY")
        self.source_date_order_combo.setCurrentIndex(
            self.source_date_order_combo.findData("MDY")
        )
        viz_layout.addWidget(self.source_date_order_combo, row, 1)
        self.update_target_timestamp_selection()
        row += 1
        
        # Add stretch to push controls to top and provide breathing room
        viz_layout.setRowStretch(row, 1)
        
        # Make Settings tab scrollable so controls have breathing room
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(viz_tab)
        scroll_area.setStyleSheet("""
            QScrollArea { border: none; background-color: #1e1e1e; }
            QScrollBar:vertical { width: 12px; }
            QScrollBar::handle:vertical { background-color: #444444; border-radius: 6px; }
            QScrollBar::handle:vertical:hover { background-color: #555555; }
        """)
        
        tab_widget.addTab(scroll_area, "Settings")
        
        # Colors Tab
        color_tab = QWidget()
        color_layout = QGridLayout(color_tab)
        
        # Sector leg lines color
        color_layout.addWidget(QLabel("Tower/Sector Legs:"), 0, 0)
        self.leg_color_button = QPushButton()
        self.leg_color = "ff000000"  # Black
        self.leg_color_button.setStyleSheet(f"background-color: {self.kml_to_qt_color(self.leg_color)}")
        self.leg_color_button.clicked.connect(lambda: self.select_color("leg"))
        color_layout.addWidget(self.leg_color_button, 0, 1)
        
        # Sector shaded area color
        color_layout.addWidget(QLabel("Tower/Sector Shaded Area:"), 1, 0)
        self.shaded_color_button = QPushButton()
        self.shaded_color = "ff00ffff"  # Yellow
        self.shaded_color_button.setStyleSheet(f"background-color: {self.kml_to_qt_color(self.shaded_color)}")
        self.shaded_color_button.clicked.connect(lambda: self.select_color("shaded"))
        color_layout.addWidget(self.shaded_color_button, 1, 1)
        
        # Distance Band color
        color_layout.addWidget(QLabel("Distance Band Color:"), 2, 0)
        self.band_color_button = QPushButton()
        self.band_color = "ff0099ff"  # Orange
        self.band_color_button.setStyleSheet(f"background-color: {self.kml_to_qt_color(self.band_color)}")
        self.band_color_button.clicked.connect(lambda: self.select_color("band"))
        color_layout.addWidget(self.band_color_button, 2, 1)
        
        # Location Point color
        color_layout.addWidget(QLabel("Location Point Color:"), 3, 0)
        self.gps_color_button = QPushButton()
        self.gps_color = "ff00ff00"  # Green
        self.gps_color_button.setStyleSheet(f"background-color: {self.kml_to_qt_color(self.gps_color)}")
        self.gps_color_button.clicked.connect(lambda: self.select_color("gps"))
        color_layout.addWidget(self.gps_color_button, 3, 1)
        
        color_layout.setRowStretch(4, 1)
        
        tab_widget.addTab(color_tab, "Colors")

        self.import_records_button = QPushButton("Import Original Records")
        self.import_records_button.setToolTip(
            "Manually map and import source records using the same workflow used for non-template files"
        )
        self.import_records_button.clicked.connect(self.open_import_records_dialog)
        tab_widget.setCornerWidget(self.import_records_button, Qt.Corner.TopRightCorner)
        
        # Set maximum height for tab widget to prevent excessive space
        tab_widget.setMaximumHeight(320)
        
        layout.addWidget(tab_widget, 2)  # Give more space to Settings tab
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar, 0)  # No stretch for progress bar
        
        # Generation actions
        self.generate_button = QPushButton("Process")
        self.generate_button.setToolTip("Process and save paired KML, GeoJSON, and TXT output files")
        self.generate_button.clicked.connect(lambda: self.generate_kml(open_viewer=False))
        self.generate_button.setMinimumHeight(30)
        self.generate_button.setMinimumWidth(145)
        self.generate_button.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                background-color: #0078d4;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
        """)

        self.viewer_button = QPushButton("Process and Open in Viewer")
        self.viewer_button.setToolTip("Process all output files, then open the GeoJSON in the included GeoLibre viewer")
        self.viewer_button.clicked.connect(lambda: self.generate_kml(open_viewer=True))
        self.viewer_button.setMinimumHeight(30)
        self.viewer_button.setMinimumWidth(188)
        self.viewer_button.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                background-color: #237a57;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #2b9168;
            }
            QPushButton:pressed {
                background-color: #195e42;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
        """)

        self.open_viewer_button = QPushButton("Open Viewer")
        self.open_viewer_button.setToolTip(
            "Open the included viewer for existing KML or GeoJSON files"
        )
        self.open_viewer_button.clicked.connect(self.open_geolibre_viewer)
        self.open_viewer_button.setMinimumHeight(30)
        self.open_viewer_button.setMinimumWidth(135)
        self.open_viewer_button.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                background-color: #596773;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #6a7a88;
            }
            QPushButton:pressed {
                background-color: #46515b;
            }
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
        """)
        self.set_generation_actions_enabled(False)
        
        # Create horizontal layout to center the actions
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.viewer_button)
        button_layout.addWidget(self.open_viewer_button)
        button_layout.addStretch()
        layout.addLayout(button_layout, 0)  # No stretch for buttons
        
        # Status text
        self.status_text = QTextEdit()
        self.status_text.setMinimumHeight(60)  # Reduced from 80
        self.status_text.setMaximumHeight(100)  # Reduced from 120
        self.status_text.setReadOnly(True)
        layout.addWidget(self.status_text, 0)  # No stretch - keep minimal
        
        # Footer with version info (clickable links)
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 2, 0, 2)  # Minimal top and bottom margins
        version_label = QLabel(f'v{APP_VERSION} | <a href="https://github.com/btc-git/OS-LOC-DAT-VIZ" style="color: #4ecdc4; text-decoration: none;">Open Source Location Data Visualizer</a> | <a href="license://show" style="color: #4ecdc4; text-decoration: none;">Licenses &amp; Notices</a>')
        version_label.setStyleSheet("color: #666666; font-size: 10px; font-style: italic;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.linkActivated.connect(self.handle_footer_link)
        
        footer_layout.addStretch()
        footer_layout.addWidget(version_label)
        footer_layout.addStretch()
        
        layout.addLayout(footer_layout, 0)  # No stretch footer
    
    def apply_dark_theme(self):
        """Apply dark theme to the application"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #404040;
                border: 1px solid #555555;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #505050;
            }
            QPushButton:pressed {
                background-color: #353535;
            }
            QPushButton:disabled {
                background-color: #2b2b2b;
                color: #666666;
            }
            QRadioButton::indicator {
                width: 18px;
                height: 18px;
            }
            QRadioButton::indicator::unchecked {
                border: 2px solid #555555;
                border-radius: 9px;
                background-color: #2b2b2b;
            }
            QRadioButton::indicator::checked {
                border: 2px solid #0078d4;
                border-radius: 9px;
                background-color: #0078d4;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #404040;
                border: 1px solid #555555;
                padding: 4px;
                border-radius: 4px;
            }
            QComboBox {
                background-color: #404040;
                border: 1px solid #555555;
                padding: 4px;
                border-radius: 4px;
                min-height: 16px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left-width: 1px;
                border-left-color: #555555;
                border-left-style: solid;
                border-top-right-radius: 3px;
                border-bottom-right-radius: 3px;
                background-color: #505050;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #ffffff;
                width: 0px;
                height: 0px;
            }
            QTabWidget::pane {
                border: 1px solid #555555;
                background-color: #2b2b2b;
            }
            QTabBar::tab {
                background-color: #404040;
                padding: 8px 12px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #0078d4;
            }
            QTabBar::tab:hover {
                background-color: #505050;
            }
            QTextEdit {
                background-color: #1e1e1e;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px;
            }
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #0078d4;
                border-radius: 3px;
            }
            QFrame {
                border: none;
            }
        """)
    
    def select_file(self):
        """Open file dialog to select CSV or Excel file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Select Input File", 
            "", 
            "CSV or Excel (*.csv *.xls *.xlsx);;All Files (*)"
        )
        
        if file_path:
            self.handle_file_selection(file_path)

    def show_import_wizard(self, file_path=None):
        """Open the advanced source-record import and mapping workflow."""
        dialog = ImportWizardDialog(self)
        if file_path:
            dialog.load_file(file_path)
        if not dialog.exec():
            return False

        self.data_file = dialog.source_path
        self.imported_dataframe = dialog.normalized_dataframe
        self.import_metadata = {
            'worksheet': dialog.selected_sheet_name,
            'header_row': dialog.selected_header_row,
            'mappings': dialog.selected_mappings,
            'date_time_filter': dialog.selected_filter_metadata,
            'cell_site_list': dialog.selected_cell_site_metadata,
        }
        filename = Path(self.data_file).name
        self.custom_label_input.clear()

        if dialog.selected_data_type == "Tower/Sector":
            self.tower_radio.setChecked(True)
            selected_radio = self.tower_radio
        elif dialog.selected_data_type == "Distance from Tower":
            self.ta_radio.setChecked(True)
            selected_radio = self.ta_radio
        else:
            self.gps_radio.setChecked(True)
            selected_radio = self.gps_radio

        for radio in (self.tower_radio, self.ta_radio, self.gps_radio):
            radio.setEnabled(radio is selected_radio)

        self.apply_import_timestamp_settings(dialog)

        self.set_generation_actions_enabled(True)
        self.file_label.setText(f"✅ Imported: {filename}")
        self.file_label.setStyleSheet("color: #00ff00; font-weight: bold;")
        self.drag_drop_widget.drop_label.setText(f"📁 Imported: {filename}\n\nReady to generate output files")
        self.add_status_message(
            f"✅ Imported {len(self.imported_dataframe)} rows as {dialog.selected_data_type} data"
        )
        cell_site_metadata = dialog.selected_cell_site_metadata
        if cell_site_metadata.get('enabled'):
            matched_rows = cell_site_metadata.get('matched_rows', 0)
            input_rows = cell_site_metadata.get('input_rows', 0)
            unmatched_rows = cell_site_metadata.get('unmatched_rows', 0)
            missing_key_rows = cell_site_metadata.get('missing_key_rows', 0)
            prefix = (
                "✅" if matched_rows == input_rows else "⚠️"
            )
            self.add_status_message(
                f"{prefix} Cell site list matched {matched_rows} of "
                f"{input_rows} original record rows"
            )
            if unmatched_rows or missing_key_rows:
                self.add_status_message(
                    f"⚠️ Cell site lookup: {unmatched_rows} rows had no match; "
                    f"{missing_key_rows} rows lacked a complete lookup key"
                )
        filter_metadata = dialog.selected_filter_metadata
        if filter_metadata.get('enabled'):
            self.add_status_message(
                f"📅 Date/time filter retained {filter_metadata['retained_rows']} of "
                f"{filter_metadata['input_rows']} rows; {filter_metadata['excluded_rows']} excluded"
            )
            if filter_metadata.get('invalid_coordinate_rows'):
                self.add_status_message(
                    f"⚠️ {filter_metadata['invalid_coordinate_rows']} retained rows have missing or "
                    "invalid mapped coordinates and cannot produce geometry"
                )
            if filter_metadata.get('unparseable_rows'):
                self.add_status_message(
                    f"⚠️ Date/time filter excluded {filter_metadata['unparseable_rows']} rows "
                    "whose timestamps could not be parsed or uniquely resolved"
                )
        return True

    def apply_import_timestamp_settings(self, dialog):
        """Mirror accepted import timestamp settings into the main controls."""
        self.set_source_timestamp_selection(
            dialog.selected_source_timezone_name,
            dialog.selected_source_offset_minutes
        )

        self.set_target_timestamp_selection(
            dialog.selected_target_timezone_name,
            dialog.selected_target_offset_minutes,
        )

        date_order_index = self.source_date_order_combo.findData(
            dialog.selected_date_order
        )
        self.source_date_order_combo.setCurrentIndex(max(date_order_index, 0))

    def set_source_timestamp_selection(self, timezone_name, offset_minutes):
        """Select a source-timezone choice by its semantic value."""
        for index in range(self.source_timezone_combo.count()):
            selection = self.source_timezone_combo.itemData(index) or {}
            if timezone_name is not None:
                matches = selection.get('timezone_name') == timezone_name
            else:
                matches = (
                    selection.get('timezone_name') is None
                    and selection.get('offset_minutes') == offset_minutes
                )
            if matches:
                self.source_timezone_combo.setCurrentIndex(index)
                return

        if timezone_name:
            self.source_timezone_combo.addItem(
                timezone_name, timezone_choice_data(timezone_name=timezone_name)
            )
            self.source_timezone_combo.setCurrentIndex(
                self.source_timezone_combo.count() - 1
            )

    def set_target_timestamp_selection(self, timezone_name, offset_minutes):
        """Select a display-timezone choice by its semantic value."""
        for index in range(self.target_timezone_combo.count()):
            selection = self.target_timezone_combo.itemData(index) or {}
            if timezone_name is not None:
                matches = selection.get('timezone_name') == timezone_name
            elif offset_minutes is None:
                matches = selection.get('no_change') is True
            else:
                matches = (
                    not selection.get('no_change')
                    and selection.get('timezone_name') is None
                    and selection.get('offset_minutes') == offset_minutes
                )
            if matches:
                self.target_timezone_combo.setCurrentIndex(index)
                return

    def update_target_timestamp_selection(self, *_args):
        """Keep generation settings synchronized with the visible control."""
        (
            self.import_target_timezone_name,
            self.import_target_offset_minutes,
        ) = ImportWizardDialog.timezone_selection(self.target_timezone_combo)

    def open_import_records_dialog(self):
        """Manual entry point to the existing import wizard workflow."""
        self.show_import_wizard()
    
    def handle_file_dropped(self, file_path):
        """Handle file dropped via drag and drop"""
        self.handle_file_selection(file_path)
    
    def handle_file_selection(self, file_path, inspected_dataframe=None):
        """Handler for file selection (both browse and drag-drop)"""
        filename = Path(file_path).name
        file_extension = Path(file_path).suffix.lower()
        if inspected_dataframe is None:
            self.data_file = file_path
            self.imported_dataframe = None
            self.import_metadata = None
            self.import_target_timezone_name = None
            self.import_target_offset_minutes = None
            self.set_target_timestamp_selection(None, None)
            self.custom_label_input.clear()
            self.set_generation_actions_enabled(False)
            self.file_label.setText(f"📄 {filename}")
            self.file_label.setStyleSheet("color: #888888; font-weight: normal;")
            self.drag_drop_widget.drop_label.setText(
                f"📁 Selected: {filename}\n\nValidating format..."
            )
            self.add_status_message(f"Selected file: {filename}")

            if file_extension in ('.xlsx', '.csv'):
                file_type = "Excel" if file_extension == '.xlsx' else "CSV"
                self.add_status_message(f"📊 Reading {file_type} headers...")
                self.start_file_inspection(file_path)
                return
        
        # Validate file format and auto-detect data type
        try:
            # Read file based on extension (with Excel date handling)
            if file_extension == '.xls':
                self.add_status_message("📊 Legacy Excel file detected - opening column mapping wizard")
                if self.show_import_wizard(file_path):
                    return
                self.set_generation_actions_enabled(False)
                self.file_label.setText(f"⚠️ {filename} (Mapping Required)")
                self.file_label.setStyleSheet("color: #ff6666; font-weight: bold;")
                self.drag_drop_widget.drop_label.setText(f"⚠️ Mapping Required: {filename}\n\nDrop or browse again to reopen the wizard")
                self.add_status_message("⚠️ Column mapping was cancelled; no data is ready for generation")
                return
            elif file_extension == '.xlsx':
                df = inspected_dataframe
            elif file_extension == '.csv':
                df = inspected_dataframe
            else:
                raise ValueError(f"Unsupported file format: {file_extension}. Please use .csv or .xlsx files.")
            
            columns = [re.sub(r'[^a-z0-9]+', ' ', str(col).lower()).strip() for col in df.columns]
            detected_type = None
            has_timestamp = 'timestamp' in columns
            
            # Check for exact template matches
            # Distance from Tower Template: Timestamp, Latitude, Longitude, Azimuth, Distance
            if (any(col in ['latitude', 'lat'] for col in columns) and
                any(col in ['longitude', 'lon', 'long'] for col in columns) and
                has_timestamp and
                any(col in ['azimuth', 'bearing', 'direction'] for col in columns) and
                any(col in ['distance', 'range', 'distance (m)', 'distance (meters)'] for col in columns)):
                detected_type = "distance_from_tower"
                self.ta_radio.setChecked(True)
                self.add_status_message("✅ Valid Distance from Tower template detected")
                
            # Tower/Sector Template: Latitude, Longitude, Timestamp, Azimuth
            elif (any(col in ['latitude', 'lat'] for col in columns) and
                  any(col in ['longitude', 'lon', 'long'] for col in columns) and
                  has_timestamp and
                  any(col in ['azimuth', 'bearing', 'direction'] for col in columns) and
                  not any(col in ['distance', 'range', 'distance (m)', 'distance (meters)'] for col in columns)):
                detected_type = "cell_tower"
                self.tower_radio.setChecked(True)
                self.add_status_message("✅ Valid Tower/Sector template detected")
                
            # Location Point Template: Latitude, Longitude, Timestamp, (optional) Accuracy
            elif (any(col in ['latitude', 'lat'] for col in columns) and
                  any(col in ['longitude', 'lon', 'long'] for col in columns) and
                  has_timestamp and
                  not any(col in ['azimuth', 'bearing', 'direction'] for col in columns)):
                detected_type = "gps"
                self.gps_radio.setChecked(True)
                self.add_status_message("✅ Valid Location Point template detected")
                if any(col in ['gps accuracy', 'accuracy', 'gps_accuracy'] for col in columns):
                    self.add_status_message("✅ Location Point Accuracy column detected - circles will be sized accordingly")
            
            # Enable generation only if valid template detected
            if detected_type:
                self.set_generation_actions_enabled(True)
                self.file_label.setText(f"✅ {filename}")
                self.file_label.setStyleSheet("color: #00ff00; font-weight: bold;")
                self.drag_drop_widget.drop_label.setText(f"📁 Ready: {filename}\n\nDrag another CSV to replace")
                
                # Enable radio button to show detection result
                if detected_type == "cell_tower":
                    self.tower_radio.setEnabled(True)
                    self.ta_radio.setEnabled(False)
                    self.gps_radio.setEnabled(False)
                elif detected_type == "distance_from_tower":
                    self.tower_radio.setEnabled(False)
                    self.ta_radio.setEnabled(True)
                    self.gps_radio.setEnabled(False)
                elif detected_type == "gps":
                    self.tower_radio.setEnabled(False)
                    self.ta_radio.setEnabled(False)
                    self.gps_radio.setEnabled(True)
            else:
                self.add_status_message("⚠️ Headers do not match a standard template - opening column mapping wizard")
                if self.show_import_wizard(file_path):
                    return

                # Mapping cancelled - disable generation and show error
                self.set_generation_actions_enabled(False)
                self.file_label.setText(f"⚠️ {filename} (Mapping Required)")
                self.file_label.setStyleSheet("color: #ff6666; font-weight: bold;")
                self.drag_drop_widget.drop_label.setText(f"⚠️ Mapping Required: {filename}\n\nDrop or browse again to reopen the wizard")
                self.add_status_message("⚠️ Column mapping was cancelled; no data is ready for generation")
                
                # Disable all radio buttons for invalid files
                self.tower_radio.setEnabled(False)
                self.ta_radio.setEnabled(False)
                self.gps_radio.setEnabled(False)
                # Clear any previous selections
                self.tower_radio.setChecked(False)
                self.ta_radio.setChecked(False)
                self.gps_radio.setChecked(False)
                
        except Exception as error:
            self.handle_file_inspection_error(file_path, str(error))

    def start_file_inspection(self, file_path):
        """Inspect source headers without blocking the main window."""
        self.pending_inspection_path = str(file_path)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.drag_drop_widget.setEnabled(False)
        self.import_records_button.setEnabled(False)

        worker = SourceFileLoadWorker(
            file_path, inspect_only=True, parent=self
        )
        self.file_inspector = worker
        worker.result_ready.connect(self.on_file_inspection_result)
        worker.load_error.connect(
            lambda message, path=str(file_path):
            self.on_file_inspection_error(path, message)
        )
        worker.finished.connect(self.on_file_inspector_finished)
        worker.start()

    def finish_file_inspection_ui(self):
        """Restore main-window controls after source inspection."""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.drag_drop_widget.setEnabled(True)
        self.import_records_button.setEnabled(True)

    def on_file_inspection_result(self, result):
        """Continue template detection after background header inspection."""
        file_path = result['file_path']
        if file_path != self.pending_inspection_path:
            return
        self.finish_file_inspection_ui()
        self.handle_file_selection(file_path, result['dataframe'])
        self.file_inspection_finished.emit(True)

    def on_file_inspection_error(self, file_path, message):
        """Report a source inspection failure and reset file controls."""
        self.finish_file_inspection_ui()
        filename = Path(file_path).name
        self.set_generation_actions_enabled(False)
        self.file_label.setText(f"❌ {filename} (Error)")
        self.file_label.setStyleSheet("color: #ff6666; font-weight: bold;")
        self.drag_drop_widget.drop_label.setText(
            f"❌ Error reading: {filename}\n\nCheck file format and try again"
        )
        self.add_status_message(f"❌ Error reading source file: {message}")
        self.add_status_message(
            "💡 Ensure the source is a valid CSV or Excel file with readable headers"
        )
        for radio in (self.tower_radio, self.ta_radio, self.gps_radio):
            radio.setEnabled(False)
            radio.setChecked(False)
        self.file_inspection_finished.emit(False)

    def on_file_inspector_finished(self):
        """Release the completed header-inspection worker."""
        if self.file_inspector:
            self.file_inspector.deleteLater()
            self.file_inspector = None
        self.pending_inspection_path = None
    
    def select_color(self, color_type):
        """Open color dialog to select colors"""
        current_color = getattr(self, f"{color_type}_color")
        qt_color = QColor(self.kml_to_qt_color(current_color))
        
        color = QColorDialog.getColor(qt_color, self, f"Select {color_type.title()} Color")
        
        if color.isValid():
            kml_color = self.qt_to_kml_color(color)
            setattr(self, f"{color_type}_color", kml_color)
            
            button = getattr(self, f"{color_type}_color_button")
            button.setStyleSheet(f"background-color: {color.name()}")
            
            self.add_status_message(f"Changed {color_type} color to {color.name()}")
    
    def kml_to_qt_color(self, kml_color):
        """Convert KML color (AABBGGRR) to Qt color format (#RRGGBB)"""
        if len(kml_color) == 8:
            r = kml_color[6:8]
            g = kml_color[4:6]
            b = kml_color[2:4]
            return f"#{r}{g}{b}"
        return "#0000ff"
    
    def qt_to_kml_color(self, qt_color):
        """Convert Qt color to KML color format (AABBGGRR)"""
        r = format(qt_color.red(), '02x')
        g = format(qt_color.green(), '02x')
        b = format(qt_color.blue(), '02x')
        return f"ff{b}{g}{r}"
    
    def add_status_message(self, message):
        """Add message to status text area"""
        self.status_text.append(f"• {message}")
        # Ensure the console always scrolls to show the latest message
        cursor = self.status_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.status_text.setTextCursor(cursor)
        self.status_text.ensureCursorVisible()
    
    def open_file_location(self, file_path):
        """Open file explorer and highlight the specified file"""
        try:
            file_path = Path(file_path).resolve()
            
            if sys.platform == 'win32':
                # Windows: Use explorer with /select flag to highlight the file
                result = subprocess.run(['explorer', '/select,', str(file_path)], 
                                      capture_output=True, text=True)
                self.add_status_message(f"📂 Opening file location: {file_path.parent}")
                
            elif sys.platform == 'darwin':
                # Possible future macOS support
                result = subprocess.run(['open', '-R', str(file_path)], check=True)
                self.add_status_message(f"📂 Opening file location: {file_path.parent}")
                
            else:
                # Possible future Linux support
                result = subprocess.run(['xdg-open', str(file_path.parent)], check=True)
                self.add_status_message(f"📂 Opening file location: {file_path.parent}")
                
        except subprocess.CalledProcessError as e:
            self.add_status_message(f"⚠️ Could not open file location: {str(e)}")
        except Exception as e:
            self.add_status_message(f"⚠️ Error opening file location: {str(e)}")
    
    def set_generation_actions_enabled(self, enabled):
        """Keep both generation actions in the same enabled state."""
        self.generate_button.setEnabled(enabled)
        self.viewer_button.setEnabled(enabled)

    def generate_kml(self, open_viewer=False):
        """Generate output files in background thread"""
        if self.kml_generator and self.kml_generator.isRunning():
            QMessageBox.warning(self, "Generation in Progress", "Wait for the current output generation to finish.")
            return
        if not self.data_file:
            QMessageBox.warning(self, "Warning", "Please select an input file first.")
            return
        
        # Determine data type
        if self.tower_radio.isChecked():
            data_type = "Tower/Sector"
        elif self.ta_radio.isChecked():
            data_type = "Distance from Tower"
        else:
            data_type = "Location Point"

        self.open_viewer_after_generation = open_viewer
        
        # Collect settings
        source_timezone_name, source_utc_offset_minutes = (
            ImportWizardDialog.timezone_selection(self.source_timezone_combo)
        )
        settings = {
            'leg_length': self.leg_length_spinbox.value(),
            'shaded_area_length': self.shaded_area_spinbox.value(),
            'azimuth_spread': self.azimuth_spinbox.value(),
            'num_points': 25,  # value for arc smoothness
            'leg_color': self.leg_color,
            'shaded_color': self.shaded_color,
            'band_color': self.band_color,
            'gps_color': self.gps_color,
            'gps_units': self.gps_units_combo.currentText(),
            'ta_distance_units': self.ta_distance_units_combo.currentText(),
            'band_thickness_before': self.inside_band_spinbox.value(),  # New: inner band distance
            'band_thickness': self.band_thickness_spinbox.value(),  # Outer band distance
            'band_thickness_units': self.band_thickness_units_combo.currentText(),
            'default_accuracy': self.default_accuracy_spinbox.value(),
            'enable_time_animation': True,  # Always enabled
            'duration_minutes': self.duration_spinbox.value(),
            'source_utc_offset_minutes': source_utc_offset_minutes,
            'source_timezone_name': source_timezone_name,
            'target_utc_offset_minutes': self.import_target_offset_minutes,
            'target_timezone_name': self.import_target_timezone_name,
            'source_date_order': self.source_date_order_combo.currentData(),
            'source_header_row': (
                self.import_metadata.get('header_row', 1)
                if self.import_metadata else 1
            ),
            'custom_label': self.custom_label_input.text().strip() or None
        }
        
        # Start generation
        self.set_generation_actions_enabled(False)
        self.open_viewer_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        self.add_status_message(f"Starting KML and GeoJSON generation for {data_type} data...")
        self.generation_messages = []
        self.current_generation_settings = settings.copy()
        self.current_generation_type = data_type
        self.current_generation_source_file = self.data_file
        self.current_import_metadata = None
        if self.import_metadata:
            self.current_import_metadata = {
                'worksheet': self.import_metadata.get('worksheet'),
                'header_row': self.import_metadata.get('header_row'),
                'mappings': dict(self.import_metadata.get('mappings', {})),
                'date_time_filter': dict(self.import_metadata.get('date_time_filter', {})),
                'cell_site_list': dict(self.import_metadata.get('cell_site_list', {})),
            }
        self.generation_started_utc = datetime.now(timezone.utc)
        
        # Create and start worker thread
        self.kml_generator = KMLGenerator(
            self.data_file, data_type, settings, dataframe=self.imported_dataframe
        )
        self.kml_generator.progress.connect(self.progress_bar.setValue)
        self.kml_generator.finished.connect(self.on_generation_finished)
        self.kml_generator.error.connect(self.on_generation_error)
        self.kml_generator.status_message.connect(self.handle_generation_status)
        self.kml_generator.start()

    def handle_generation_status(self, message):
        """Display and retain messages produced by the active generation run."""
        self.generation_messages.append(message)
        self.add_status_message(message)
    
    def on_generation_finished(self, output_payload):
        """Handle successful KML/GeoJSON generation"""
        self.progress_bar.setVisible(False)
        open_viewer = self.open_viewer_after_generation
        self.open_viewer_after_generation = False

        if isinstance(output_payload, dict):
            kml_content = output_payload.get('kml', '')
            geojson_content = output_payload.get('geojson', '')
        else:
            # Backward compatibility with older worker payload.
            kml_content = output_payload or ''
            geojson_content = ''
        
        # Show file save dialog
        base_name = Path(self.current_generation_source_file).stem
        
        # Use custom label for filename if provided, otherwise use base name
        custom_label = self.custom_label_input.text().strip()
        if custom_label:
            # Clean custom label for filename
            safe_label = "".join(c for c in custom_label if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_label = safe_label.replace(' ', '_')
            suggested_filename = f"{safe_label}.geojson"
        else:
            suggested_filename = f"{base_name}_visualization.geojson"
            
        start_dir = str(Path(self.current_generation_source_file).parent / suggested_filename)
        
        selected_output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save Processed Data Files",
            start_dir,
            "GeoJSON Files (*.geojson)"
        )
        
        if selected_output_file:
            try:
                output_path, geojson_path = self.write_visualization_outputs(
                    selected_output_file, kml_content, geojson_content
                )
                self.add_status_message(
                    f"✅ KML file saved successfully: {output_path.name}"
                )
                self.add_status_message(
                    f"✅ GeoJSON file saved successfully: {geojson_path.name}"
                )
            except Exception as e:
                self.set_generation_actions_enabled(True)
                self.open_viewer_button.setEnabled(True)
                self.add_status_message(f"❌ Error saving file: {str(e)}")
                QMessageBox.critical(
                    self,
                    "Save Error",
                    f"Failed to save output file(s):\n\n{str(e)}"
                )
                return

            log_path = output_path.with_suffix('.txt')
            try:
                log_path.write_text(self.build_generation_log(output_path), encoding='utf-8')
                self.add_status_message(f"✅ Generation log saved: {log_path.name}")
            except Exception as e:
                self.add_status_message(f"⚠️ Output files were saved, but the generation log could not be saved: {str(e)}")
                QMessageBox.warning(
                    self,
                    "Log Save Warning",
                    f"The output files were saved, but their generation log could not be saved:\n\n{str(e)}"
                )

            if open_viewer:
                self.start_geolibre_viewer(geojson_path)
            else:
                self.set_generation_actions_enabled(True)
                self.open_viewer_button.setEnabled(True)
                self.open_file_location(geojson_path)
        else:
            self.set_generation_actions_enabled(True)
            self.open_viewer_button.setEnabled(True)
            self.add_status_message("⚠️ File save cancelled by user")

    def open_geolibre_viewer(self):
        """Open a clean viewer session for existing KML or GeoJSON files."""
        self.start_geolibre_viewer()

    def start_geolibre_viewer(self, geojson_path=None):
        """Prepare and launch the bundled GeoLibre viewer in the background."""
        if self.viewer_launcher is not None:
            QMessageBox.information(
                self,
                "Viewer Is Opening",
                "Wait for the included viewer to finish opening.",
            )
            return

        self.pending_viewer_geojson_path = (
            Path(geojson_path) if geojson_path is not None else None
        )
        self.restore_generation_actions_after_viewer = (
            geojson_path is not None or self.generate_button.isEnabled()
        )
        self.set_generation_actions_enabled(False)
        self.open_viewer_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)
        self.add_status_message("Preparing the included GeoLibre viewer...")

        display_name = None
        if geojson_path is not None:
            display_name = self.current_generation_settings.get('custom_label') or Path(geojson_path).stem
        self.viewer_launcher = GeoLibreLaunchWorker(geojson_path, display_name, self)
        self.viewer_launcher.launched.connect(self.on_geolibre_viewer_launched)
        self.viewer_launcher.error.connect(self.on_geolibre_viewer_error)
        self.viewer_launcher.finished.connect(self.on_geolibre_viewer_thread_finished)
        self.viewer_launcher.start()

    def on_geolibre_viewer_launched(self, project_path):
        """Restore the UI after GeoLibre accepts the generated project."""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.set_generation_actions_enabled(self.restore_generation_actions_after_viewer)
        self.open_viewer_button.setEnabled(True)
        opened_generated_output = self.pending_viewer_geojson_path is not None
        self.pending_viewer_geojson_path = None
        if opened_generated_output:
            self.add_status_message(
                f"✅ Opened generated data in GeoLibre: {Path(project_path).name}"
            )
        else:
            self.add_status_message(
                "✅ Opened GeoLibre; drag one or more KML or GeoJSON files into the viewer"
            )

    def on_geolibre_viewer_error(self, error_message):
        """Report viewer setup errors without losing the generated outputs."""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.set_generation_actions_enabled(self.restore_generation_actions_after_viewer)
        self.open_viewer_button.setEnabled(True)
        generated_output_path = self.pending_viewer_geojson_path
        if generated_output_path:
            status_message = f"⚠️ Output files were saved, but GeoLibre could not open: {error_message}"
            dialog_message = (
                "The output files were saved, but the included GeoLibre viewer could not be opened:\n\n"
                f"{error_message}"
            )
        else:
            status_message = f"⚠️ The included GeoLibre viewer could not open: {error_message}"
            dialog_message = f"The included GeoLibre viewer could not be opened:\n\n{error_message}"
        self.add_status_message(status_message)
        QMessageBox.warning(
            self,
            "Viewer Launch Warning",
            dialog_message,
        )
        if generated_output_path:
            self.open_file_location(generated_output_path)
        self.pending_viewer_geojson_path = None

    def on_geolibre_viewer_thread_finished(self):
        """Release the completed viewer launch worker."""
        if self.viewer_launcher:
            self.viewer_launcher.deleteLater()
            self.viewer_launcher = None

    @staticmethod
    def write_visualization_outputs(output_file, kml_content, geojson_content):
        """Write the required KML and GeoJSON siblings for one generation."""
        if not kml_content:
            raise ValueError("Generated KML content is empty")
        if not geojson_content:
            raise ValueError("Generated GeoJSON content is empty")

        selected_path = Path(output_file)
        if selected_path.suffix.lower() == '.geojson':
            geojson_path = selected_path
            output_path = selected_path.with_suffix('.kml')
        else:
            output_path = selected_path.with_suffix('.kml')
            geojson_path = selected_path.with_suffix('.geojson')
        output_path.write_text(kml_content, encoding='utf-8')
        geojson_path.write_text(geojson_content, encoding='utf-8')
        return output_path, geojson_path

    @staticmethod
    def calculate_file_sha256(file_path):
        """Calculate a SHA-256 digest without loading the entire file into memory."""
        digest = hashlib.sha256()
        with open(file_path, 'rb') as file_handle:
            for chunk in iter(lambda: file_handle.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def build_generation_log(self, output_file):
        """Create the human-readable audit log for the completed generation."""
        output_path = Path(output_file)
        geojson_path = output_path.with_suffix('.geojson')
        source_path = Path(self.current_generation_source_file)
        source_hash = self.calculate_file_sha256(source_path)
        output_hash = self.calculate_file_sha256(output_path)
        geojson_hash = self.calculate_file_sha256(geojson_path) if geojson_path.exists() else 'Not generated'
        completed_utc = datetime.now(timezone.utc)
        settings = self.current_generation_settings
        summary = self.kml_generator.audit_summary if self.kml_generator else {}

        timezone_value = settings.get('source_timezone_name')
        if timezone_value:
            timezone_description = timezone_value
        else:
            offset_minutes = int(settings.get('source_utc_offset_minutes', 0))
            sign = '+' if offset_minutes >= 0 else '-'
            hours, minutes = divmod(abs(offset_minutes), 60)
            timezone_description = f"Fixed UTC {sign}{hours:02d}:{minutes:02d}"

        lines = [
            "Open Source Location Data Visualizer - Generation Log",
            "All outputs are preliminary and require independent expert review.",
            "",
            f"Application version: {APP_VERSION}",
            f"Generation started (UTC): {self.generation_started_utc.isoformat() if self.generation_started_utc else 'Unknown'}",
            f"Generation completed (UTC): {completed_utc.isoformat()}",
            f"Source file: {source_path.name}",
            f"Source SHA-256: {source_hash}",
            f"Output KML: {output_path.name}",
            f"Output KML SHA-256: {output_hash}",
            f"Output GeoJSON: {geojson_path.name if geojson_path.exists() else 'Not generated'}",
            f"Output GeoJSON SHA-256: {geojson_hash}",
            f"Input workflow: {'Import Wizard' if self.current_import_metadata else 'Template/direct file'}",
            f"Record type: {self.current_generation_type}",
            "",
            "Timestamp interpretation",
            f"Timezone: {timezone_description}",
            f"Slash/dash date order: {settings.get('source_date_order', 'MDY')}",
            f"Animation duration (minutes): {settings.get('duration_minutes', 30)}",
        ]

        if self.current_import_metadata:
            lines.extend([
                "",
                "Import mapping",
                f"Worksheet: {self.current_import_metadata.get('worksheet') or 'Not applicable'}",
                f"Header row: {self.current_import_metadata.get('header_row')}",
            ])
            for target_field, source_column in self.current_import_metadata.get('mappings', {}).items():
                lines.append(f"{target_field}: {source_column}")
            cell_site_metadata = self.current_import_metadata.get(
                'cell_site_list', {}
            )
            if cell_site_metadata.get('enabled'):
                cell_site_path_value = cell_site_metadata.get('file_path')
                cell_site_path = (
                    Path(cell_site_path_value) if cell_site_path_value else None
                )
                cell_site_hash = (
                    self.calculate_file_sha256(cell_site_path)
                    if cell_site_path and cell_site_path.is_file()
                    else 'Unavailable'
                )
                lines.extend([
                    "",
                    "Cell site list",
                    f"Cell site list file: {cell_site_metadata.get('file_name') or (cell_site_path.name if cell_site_path else 'Unknown')}",
                    f"Cell site list SHA-256: {cell_site_hash}",
                    f"Worksheet: {cell_site_metadata.get('worksheet') or 'Not applicable'}",
                    f"Header row: {cell_site_metadata.get('header_row')}",
                    f"Value priority: {cell_site_metadata.get('policy_label') or cell_site_metadata.get('policy')}",
                    "Original-record lookup mapping:",
                ])
                for role, source_column in cell_site_metadata.get(
                    'original_key_mappings', {}
                ).items():
                    lines.append(f"{role}: {source_column}")
                lines.append("Cell-site-list mapping:")
                for role, source_column in cell_site_metadata.get(
                    'cell_site_mappings', {}
                ).items():
                    lines.append(f"{role}: {source_column}")
                lines.extend([
                    f"Original rows evaluated: {cell_site_metadata.get('input_rows', 'Unknown')}",
                    f"Cell site list rows: {cell_site_metadata.get('cell_site_rows', 'Unknown')}",
                    f"Cell site list rows ignored - missing lookup key: {cell_site_metadata.get('cell_site_rows_ignored_missing_key', 'Unknown')}",
                    f"Original rows matched to cell site list: {cell_site_metadata.get('matched_rows', 'Unknown')}",
                    f"Original rows unmatched in cell site list: {cell_site_metadata.get('unmatched_rows', 'Unknown')}",
                    f"Original source rows unmatched in cell site list: {self.format_audit_row_numbers(cell_site_metadata.get('unmatched_source_rows', []), cell_site_metadata.get('unmatched_rows', 0))}",
                    f"Original rows missing a lookup key: {cell_site_metadata.get('missing_key_rows', 'Unknown')}",
                    f"Original source rows missing a lookup key: {self.format_audit_row_numbers(cell_site_metadata.get('missing_key_source_rows', []), cell_site_metadata.get('missing_key_rows', 0))}",
                ])
                for field in ('Latitude', 'Longitude', 'Azimuth'):
                    lines.extend([
                        f"{field} values from cell site list: {cell_site_metadata.get('fields_from_cell_site_list', {}).get(field, 'Unknown')}",
                        f"{field} values from original records: {cell_site_metadata.get('fields_from_original_records', {}).get(field, 'Unknown')}",
                        f"{field} values left missing: {cell_site_metadata.get('fields_left_missing', {}).get(field, 'Unknown')}",
                    ])
            filter_metadata = self.current_import_metadata.get('date_time_filter', {})
            if filter_metadata.get('enabled'):
                lines.extend([
                    "",
                    "Import date/time filter",
                    f"Boundary mode: {'Exact date/time' if filter_metadata.get('exact_times') else 'Whole days'}",
                    f"Source range (inclusive): {filter_metadata.get('start_source')} through {filter_metadata.get('end_source')}",
                    f"UTC range (inclusive): {filter_metadata.get('start_utc')} through {filter_metadata.get('end_utc')}",
                    f"Rows before filter: {filter_metadata.get('input_rows')}",
                    f"Rows retained: {filter_metadata.get('retained_rows')}",
                    f"Rows excluded: {filter_metadata.get('excluded_rows')}",
                    f"Rows excluded with unparseable or unresolved timestamps: {filter_metadata.get('unparseable_rows')}",
                    f"Retained rows with valid mapped coordinates: {filter_metadata.get('valid_coordinate_rows')}",
                    f"Retained rows with missing or invalid mapped coordinates: {filter_metadata.get('invalid_coordinate_rows')}",
                ])

        lines.extend([
            "",
            "Visualization settings",
            f"Leg length (miles): {settings.get('leg_length')}",
            f"Shaded area length (miles): {settings.get('shaded_area_length')}",
            f"Sector width (degrees): {settings.get('azimuth_spread')}",
            f"Distance units: {settings.get('ta_distance_units')}",
            f"Inner band extension: {settings.get('band_thickness_before')} {settings.get('band_thickness_units')}",
            f"Outer band extension: {settings.get('band_thickness')} {settings.get('band_thickness_units')}",
            f"Location accuracy units: {settings.get('gps_units')}",
            f"Default location accuracy: {settings.get('default_accuracy')} {settings.get('gps_units')}",
            f"Leg color (KML AABBGGRR): {settings.get('leg_color')}",
            f"Shaded area color (KML AABBGGRR): {settings.get('shaded_color')}",
            f"Distance band color (KML AABBGGRR): {settings.get('band_color')}",
            f"Location point color (KML AABBGGRR): {settings.get('gps_color')}",
            f"Custom label: {settings.get('custom_label') or 'None'}",
            "",
            "Row outcomes",
            f"Input rows: {summary.get('input_rows', 'Unknown')}",
            f"Generated rows: {summary.get('generated_rows', 'Unknown')}",
            f"Skipped - invalid coordinates: {summary.get('skipped_invalid_coordinates', 'Unknown')}",
            f"Skipped - missing timestamp: {summary.get('skipped_missing_timestamp', 'Unknown')}",
            f"Skipped - DST conflict: {summary.get('skipped_dst_conflict', 'Unknown')}",
            "",
            "Generation warnings",
        ])
        if self.generation_messages:
            lines.extend(self.generation_messages)
        else:
            lines.append("None")

        return "\n".join(lines) + "\n"

    @staticmethod
    def format_audit_row_numbers(row_numbers, total_count):
        """Format bounded physical row references without copying source values."""
        if not row_numbers:
            return "None"
        row_text = ", ".join(str(row_number) for row_number in row_numbers)
        if total_count > len(row_numbers):
            return f"{row_text} (first {len(row_numbers)} of {total_count})"
        return row_text
    
    def on_generation_error(self, error_message):
        """Handle KML generation error"""
        self.progress_bar.setVisible(False)
        self.set_generation_actions_enabled(True)
        self.open_viewer_button.setEnabled(True)
        self.open_viewer_after_generation = False
        
        self.add_status_message(f"❌ Error: {error_message}")
        
        QMessageBox.critical(
            self, 
            "Error", 
            f"Failed to generate output file(s):\n\n{error_message}"
        )
    
    def show_template_menu(self):
        """Show context menu with template options"""
        menu = QMenu(self)
        
        # Tower/Sector template
        tower_action = menu.addAction("📶 Tower/Sector Template")
        tower_action.triggered.connect(lambda: self.download_template("cell_tower"))
        
        # Distance from Tower template
        ta_action = menu.addAction("📏 Distance from Tower Template")
        ta_action.triggered.connect(lambda: self.download_template("distance_from_tower"))
        
        # Point Location template
        gps_action = menu.addAction("📌 Location Point Template")
        gps_action.triggered.connect(lambda: self.download_template("gps"))
        
        # Show menu below the button
        menu.exec(self.template_button.mapToGlobal(self.template_button.rect().bottomLeft()))
    
    def download_template(self, template_type):
        """Download a specific XLSX template with pre-formatted columns"""
        from datetime import datetime
        
        # Define template/sample data
        templates = {
            "cell_tower": {
                "filename": "tower_sector_template.xlsx",
                "headers": ["Timestamp", "Latitude", "Longitude", "Azimuth"],
                "sample_data": [
                    [datetime(2024, 1, 15, 14, 0, 0), 43.15831, -77.60938, 240],
                    [datetime(2024, 1, 15, 14, 15, 0), 43.15831, -77.60938, 240],
                    [datetime(2024, 1, 15, 14, 30, 0), 43.15400, -77.61390, 335],
                    [datetime(2024, 1, 15, 14, 45, 0), 43.15470, -77.63213, 90],
                    [datetime(2024, 1, 15, 15, 0, 0), 43.16109, -77.65102, 180],
                    [datetime(2024, 1, 15, 15, 15, 0), 43.16260, -77.67418, 180],
                    [datetime(2024, 1, 15, 15, 30, 0), 43.15831, -77.60938, 240],
                    [datetime(2024, 1, 15, 15, 45, 0), 43.15400, -77.61390, 335],
                    [datetime(2024, 1, 15, 16, 0, 0), 43.15470, -77.63213, 90],
                    [datetime(2024, 1, 15, 16, 15, 0), 43.16109, -77.65102, 180]
                ],
                "description": "Tower/Sector Data Template"
            },

            "distance_from_tower": {
                "filename": "distance_from_tower_template.xlsx",
                "headers": ["Timestamp", "Latitude", "Longitude", "Azimuth", "Distance"],
                "sample_data": [
                    [datetime(2024, 1, 15, 14, 0, 0), 43.15831, -77.60938, 240, 0.8],
                    [datetime(2024, 1, 15, 14, 3, 0), 43.15831, -77.60938, 240, 1.1],
                    [datetime(2024, 1, 15, 14, 6, 0), 43.15400, -77.61390, 335, 0.4],
                    [datetime(2024, 1, 15, 14, 9, 0), 43.15470, -77.63213, 90, 3.4],
                    [datetime(2024, 1, 15, 14, 12, 0), 43.16109, -77.65102, 180, 1.7],
                    [datetime(2024, 1, 15, 14, 15, 0), 43.16260, -77.67418, 180, 2.5],
                    [datetime(2024, 1, 15, 14, 18, 0), 43.15831, -77.60938, 240, 4.2],
                    [datetime(2024, 1, 15, 14, 21, 0), 43.15400, -77.61390, 335, 1.3],
                    [datetime(2024, 1, 15, 14, 24, 0), 43.15470, -77.63213, 90, 0.5],
                    [datetime(2024, 1, 15, 14, 27, 0), 43.16109, -77.65102, 180, 1.8]
                ],
                "description": "Distance from Tower Data Template"
            },

            "gps": {
                "filename": "location_point_template.xlsx",
                "headers": ["Timestamp", "Latitude", "Longitude", "Accuracy"],
                "sample_data": [
                    [datetime(2024, 1, 15, 14, 0, 0), 43.156622, -77.608895, 250],
                    [datetime(2024, 1, 15, 14, 1, 0), 43.157830, -77.605310, 200],
                    [datetime(2024, 1, 15, 14, 2, 0), 43.158941, -77.601745, 150],
                    [datetime(2024, 1, 15, 14, 3, 0), 43.159756, -77.594527, 300],
                    [datetime(2024, 1, 15, 14, 4, 0), 43.161422, -77.591803, 200],
                    [datetime(2024, 1, 15, 14, 5, 0), 43.163650, -77.590300, 150],
                    [datetime(2024, 1, 15, 14, 6, 0), 43.166050, -77.589700, 100],
                    [datetime(2024, 1, 15, 14, 7, 0), 43.168453, -77.589232, 500],
                    [datetime(2024, 1, 15, 14, 8, 0), 43.167950, -77.589800, 200],
                    [datetime(2024, 1, 15, 14, 9, 0), 43.167541, -77.590212, 150]
                ],
                "description": "Location Point Template"
            }
        }
        
        if template_type not in templates:
            return
        
        template = templates[template_type]
        
        # Show save dialog
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            f"Save {template['description']}",
            template['filename'],
            "Excel Files (*.xlsx);;All Files (*)"
        )
        
        if output_file:
            try:
                # Create workbook with openpyxl for proper formatting
                wb = Workbook()
                ws = wb.active
                # Excel sheet names cannot contain: \ / ? * [ ]
                safe_title = template['description'].replace('/', '-').replace('\\', '-')
                ws.title = safe_title[:31]
                
                # Write headers with bold font
                header_font = Font(bold=True)
                for col_idx, header in enumerate(template['headers'], 1):
                    cell = ws.cell(row=1, column=col_idx, value=header)
                    cell.font = header_font
                
                # Write sample data
                timestamp_col = template['headers'].index('Timestamp') + 1  # 1-based
                for row_idx, row_data in enumerate(template['sample_data'], 2):
                    for col_idx, value in enumerate(row_data, 1):
                        cell = ws.cell(row=row_idx, column=col_idx, value=value)
                        # Format timestamp column to show seconds
                        if col_idx == timestamp_col:
                            cell.number_format = 'YYYY-MM-DD HH:MM:SS'
                
                # Auto-fit column widths
                for col_idx, header in enumerate(template['headers'], 1):
                    # Set reasonable widths based on content
                    if header == 'Timestamp':
                        ws.column_dimensions[chr(64 + col_idx)].width = 22
                    elif header in ('Latitude', 'Longitude'):
                        ws.column_dimensions[chr(64 + col_idx)].width = 14
                    else:
                        ws.column_dimensions[chr(64 + col_idx)].width = 12
                
                wb.save(output_file)
                
                self.add_status_message(f"✅ Template saved: {Path(output_file).name}")
                
                # Open file location
                self.open_file_location(output_file)
                
                # Show info about the template
                QMessageBox.information(
                    self,
                    "Template Downloaded",
                    f"{template['description']} has been saved.\n\n"
                    f"The template includes:\n"
                    f"• Required column headers: {', '.join(template['headers'])}\n"
                    f"• Sample data rows to show the expected format\n"
                    f"• Timestamp column pre-formatted to show seconds (HH:MM:SS)\n\n"
                    f"Replace the sample data with your own data and save. "
                    f"You can also load this sample file directly to see how the visualizer works."
                )
                
            except Exception as e:
                self.add_status_message(f"❌ Error saving template: {str(e)}")
                QMessageBox.critical(
                    self,
                    "Save Error",
                    f"Failed to save template file:\n\n{str(e)}"
                )
        else:
            self.add_status_message("⚠️ Template download cancelled")
    
    def create_pushpin_icon(self):
        """Create a traditional WiFi icon for the application"""
        # Create a 32x32 pixel icon
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Set up the center point and base styling
        center_x, center_y = 16, 20
        
        # Draw the base point (device/router)
        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        painter.setBrush(Qt.GlobalColor.darkBlue)
        painter.drawEllipse(center_x - 2, center_y - 1, 4, 3)
        
        # Draw WiFi signal arcs (3 concentric arcs)
        painter.setBrush(Qt.GlobalColor.transparent)
        
        # Arc settings: radius, line width, color
        arcs = [
            (6, 2, Qt.GlobalColor.darkGreen),    # Inner arc
            (10, 2, Qt.GlobalColor.green),       # Middle arc
            (14, 2, Qt.GlobalColor.darkGray)     # Outer arc
        ]
        
        for radius, width, color in arcs:
            painter.setPen(QPen(color, width))
            # Draw arc from -60 to +60 degrees (120 degree span)
            painter.drawArc(
                center_x - radius, center_y - radius,
                radius * 2, radius * 2,
                30 * 16, 120 * 16  # Qt uses 16ths of degrees
            )
        
        painter.end()
        
        return QIcon(pixmap)
