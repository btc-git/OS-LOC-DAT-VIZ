"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import pandas as pd
import subprocess
import sys
from pathlib import Path
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGridLayout, QPushButton, QLabel, QFileDialog, 
                             QSpinBox, QDoubleSpinBox, QRadioButton, QButtonGroup, 
                             QTextEdit, QGroupBox, QColorDialog, QProgressBar, 
                             QMessageBox, QTabWidget, QCheckBox, QMenu, QComboBox, QLineEdit)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont, QColor, QIcon, QPixmap, QPainter, QPen

from dialogs import DisclaimerDialog
from widgets import DragDropWidget
from kml_generator import KMLGenerator


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Open Source Location Data Visualizer")
        self.setGeometry(100, 100, 600, 820)  # Increased from 780 to 820 for more comfortable spacing
        
        # Set custom window icon
        self.setWindowIcon(self.create_pushpin_icon())
        
        # Initialize variables
        self.data_file = None
        self.kml_generator = None
        self.settings = QSettings("OpenSource", "LocationDataVisualizer")
        
        # Set up UI
        self.setup_ui()
        self.apply_dark_theme()
        
        # Show disclaimer dialog on startup
        self.show_disclaimer_dialog()
        
        # Add welcome message
        self.add_status_message("To get started, download a template file using the '📁 Templates' button.")
        self.add_status_message("Replace the sample data in the template with your own data and save it as a CSV or XLSX file.")
        self.add_status_message("Drag and drop your CSV or XLSX file, or click 'Browse for File', to load it into the visualizer.")
        self.add_status_message("Adjust Settings and Colors as needed, then click 'Generate KML File' to create the KML.")
        self.add_status_message("The KML file can be opened in Google Earth, Google My Maps, Google Earth Pro, or other kml-viewers.")


    
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
        self.template_button.setToolTip("Download template CSV files with correct headers for each data type")
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
        
        custom_label_desc = QLabel("Custom label for Google Earth (optional):")
        custom_label_desc.setStyleSheet("color: #888888; font-style: italic; font-size: 11px;")
        label_layout.addWidget(custom_label_desc)
        
        self.custom_label_input = QLineEdit()
        self.custom_label_input.setPlaceholderText("e.g., 'August 1 Warrant - Timing Advance'")
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
        viz_layout.setVerticalSpacing(10)
        
        # Leg length
        leg_length_label = QLabel("Tower/Sector Leg Length (miles):")
        leg_length_label.setToolTip("Length of the lines extending from the tower")
        viz_layout.addWidget(leg_length_label, 0, 0)
        self.leg_length_spinbox = QDoubleSpinBox()
        self.leg_length_spinbox.setRange(0.5, 20.0)
        self.leg_length_spinbox.setValue(3.0)
        self.leg_length_spinbox.setSingleStep(0.5)
        viz_layout.addWidget(self.leg_length_spinbox, 0, 1)
        
        # Shaded area length
        shaded_area_label = QLabel("Tower/Sector Shaded Area Length (miles):")
        shaded_area_label.setToolTip("Length of the shaded wedge (can be shorter or equal to leg length)")
        viz_layout.addWidget(shaded_area_label, 1, 0)
        self.shaded_area_spinbox = QDoubleSpinBox()
        self.shaded_area_spinbox.setRange(0.1, 10.0)
        self.shaded_area_spinbox.setValue(1.0)
        self.shaded_area_spinbox.setSingleStep(0.1)
        viz_layout.addWidget(self.shaded_area_spinbox, 1, 1)
        
        # Shaded area azimuth and width
        azimuth_label = QLabel("Tower/Sector Width (degrees):")
        azimuth_label.setToolTip("Angular width of the tower sector shaded area")
        viz_layout.addWidget(azimuth_label, 2, 0)
        self.azimuth_spinbox = QSpinBox()
        self.azimuth_spinbox.setRange(30, 360)
        self.azimuth_spinbox.setValue(120)
        viz_layout.addWidget(self.azimuth_spinbox, 2, 1)
        
        # Location Point accuracy units dropdown
        gps_units_label = QLabel("Location Point Accuracy Units:")
        gps_units_label.setToolTip("Select the units used for location point accuracy in your data")
        viz_layout.addWidget(gps_units_label, 3, 0)
        self.gps_units_combo = QComboBox()
        self.gps_units_combo.addItems(["Meters", "Feet", "Miles", "Kilometers"])
        self.gps_units_combo.setCurrentText("Meters")  # Default to meters
        viz_layout.addWidget(self.gps_units_combo, 3, 1)
        
        # Default Location Point accuracy for missing data
        default_accuracy_label = QLabel("Default Location Accuracy:")
        default_accuracy_label.setToolTip("Default accuracy radius used when input location point data has no accuracy value (uses Location Point Accuracy Units above)")
        viz_layout.addWidget(default_accuracy_label, 4, 0)
        self.default_accuracy_spinbox = QSpinBox()
        self.default_accuracy_spinbox.setRange(1, 10000)
        self.default_accuracy_spinbox.setValue(100)  # Default 100
        viz_layout.addWidget(self.default_accuracy_spinbox, 4, 1)
        
        # Distance from Tower units dropdown
        ta_distance_units_label = QLabel("Distance from Tower Units:")
        ta_distance_units_label.setToolTip("Select the units used for distance from tower in your data")
        viz_layout.addWidget(ta_distance_units_label, 5, 0)
        self.ta_distance_units_combo = QComboBox()
        self.ta_distance_units_combo.addItems(["Meters", "Feet", "Miles", "Kilometers"])
        self.ta_distance_units_combo.setCurrentText("Miles")  # Default to miles for distance from tower
        viz_layout.addWidget(self.ta_distance_units_combo, 5, 1)
        
        # Duration setting for time animation
        duration_label = QLabel("Animation Duration (minutes):")
        duration_label.setToolTip("How long each visualization stays visible during time animation (end time = start time + duration)")
        viz_layout.addWidget(duration_label, 6, 0)
        self.duration_spinbox = QSpinBox()
        self.duration_spinbox.setRange(1, 1440)  # 1 minute to 24 hours
        self.duration_spinbox.setValue(30)  # Default to 30 minutes
        viz_layout.addWidget(self.duration_spinbox, 6, 1)
        
        
        tab_widget.addTab(viz_tab, "Settings")
        
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
        
        # Distance from Tower color
        color_layout.addWidget(QLabel("Distance from Tower Arc Color:"), 2, 0)
        self.ta_color_button = QPushButton()
        self.ta_color = "ff0000ff"  # Red
        self.ta_color_button.setStyleSheet(f"background-color: {self.kml_to_qt_color(self.ta_color)}")
        self.ta_color_button.clicked.connect(lambda: self.select_color("ta"))
        color_layout.addWidget(self.ta_color_button, 2, 1)
        
        # Location Point color
        color_layout.addWidget(QLabel("Location Point Color:"), 3, 0)
        self.gps_color_button = QPushButton()
        self.gps_color = "ff00ff00"  # Green
        self.gps_color_button.setStyleSheet(f"background-color: {self.kml_to_qt_color(self.gps_color)}")
        self.gps_color_button.clicked.connect(lambda: self.select_color("gps"))
        color_layout.addWidget(self.gps_color_button, 3, 1)
        
        color_layout.setRowStretch(4, 1)
        
        tab_widget.addTab(color_tab, "Colors")
        
        # Set maximum height for tab widget to prevent excessive space
        tab_widget.setMaximumHeight(320)
        
        layout.addWidget(tab_widget, 0)  # No stretch for tabs
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar, 0)  # No stretch for progress bar
        
        # Generate button
        self.generate_button = QPushButton("Generate KML File")
        self.generate_button.clicked.connect(self.generate_kml)
        self.generate_button.setEnabled(False)
        self.generate_button.setMinimumHeight(30)
        self.generate_button.setMinimumWidth(200)
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
        
        # Create horizontal layout to center the button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.generate_button)
        button_layout.addStretch()
        layout.addLayout(button_layout, 0)  # No stretch for button
        
        # Status text
        self.status_text = QTextEdit()
        self.status_text.setMinimumHeight(80)
        self.status_text.setReadOnly(True)
        layout.addWidget(self.status_text, 1)  # Add stretch to fill remaining space
        
        # Footer with version info (clickable links)
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 5, 0, 5) # top and bottom margins
        version_label = QLabel('v1.0 | <a href="https://github.com/btc-git/OS-LOC-DAT-VIZ" style="color: #4ecdc4; text-decoration: none;">Open Source Location Data Visualizer</a> | <a href="license://show" style="color: #4ecdc4; text-decoration: none;">GPL v3.0</a>')
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
            "CSV or XLSX (*.csv *.xlsx);;All Files (*)"
        )
        
        if file_path:
            self.handle_file_selection(file_path)
    
    def handle_file_dropped(self, file_path):
        """Handle file dropped via drag and drop"""
        self.handle_file_selection(file_path)
    
    def handle_file_selection(self, file_path):
        """Handler for file selection (both browse and drag-drop)"""
        self.data_file = file_path
        filename = Path(file_path).name
        
        # Clear custom label field for new file
        self.custom_label_input.clear()
        
        # Update UI with file selected
        self.file_label.setText(f"📄 {filename}")
        self.file_label.setStyleSheet("color: #888888; font-weight: normal;")
        
        # Update drag-drop widget to show selected file
        self.drag_drop_widget.drop_label.setText(f"📁 Selected: {filename}\n\nValidating format...")
        
        self.add_status_message(f"Selected file: {filename}")
        
        # Validate file format and auto-detect data type
        try:
            # Read file based on extension (with Excel date handling)
            file_extension = Path(file_path).suffix.lower()
            if file_extension == '.xlsx':
                df = pd.read_excel(file_path, nrows=1, engine='openpyxl')
                self.add_status_message("📊 Reading Excel file...")
            elif file_extension == '.csv':
                df = pd.read_csv(file_path, nrows=1)
                self.add_status_message("📄 Reading CSV file...")
            else:
                raise ValueError(f"Unsupported file format: {file_extension}. Please use .csv or .xlsx files.")
            
            columns = [col.lower().strip() for col in df.columns]
            detected_type = None
            
            # Check for exact template matches
            # Distance from Tower Template: Timestamp, Latitude, Longitude, Azimuth, Distance
            if (any(col in ['latitude', 'lat'] for col in columns) and
                any(col in ['longitude', 'lon', 'long'] for col in columns) and
                any(col in ['timestamp', 'date & time', 'datetime', 'time'] for col in columns) and
                any(col in ['azimuth', 'bearing', 'direction'] for col in columns) and
                any(col in ['distance', 'range', 'distance (m)', 'distance (meters)'] for col in columns)):
                detected_type = "timing_advance"
                self.ta_radio.setChecked(True)
                self.add_status_message("✅ Valid Distance from Tower template detected")
                
            # Tower/Sector Template: Latitude, Longitude, Timestamp, Azimuth
            elif (any(col in ['latitude', 'lat'] for col in columns) and
                  any(col in ['longitude', 'lon', 'long'] for col in columns) and
                  any(col in ['timestamp', 'date & time', 'datetime', 'time'] for col in columns) and
                  any(col in ['azimuth', 'bearing', 'direction'] for col in columns) and
                  not any(col in ['distance', 'range', 'distance (m)', 'distance (meters)'] for col in columns)):
                detected_type = "cell_tower"
                self.tower_radio.setChecked(True)
                self.add_status_message("✅ Valid Tower/Sector template detected")
                
            # Location Point Template: Latitude, Longitude, Timestamp, (optional) Accuracy
            elif (any(col in ['latitude', 'lat'] for col in columns) and
                  any(col in ['longitude', 'lon', 'long'] for col in columns) and
                  any(col in ['timestamp', 'date & time', 'datetime', 'time'] for col in columns) and
                  not any(col in ['azimuth', 'bearing', 'direction'] for col in columns)):
                detected_type = "gps"
                self.gps_radio.setChecked(True)
                self.add_status_message("✅ Valid Location Point template detected")
                if any(col in ['gps accuracy', 'accuracy', 'gps_accuracy'] for col in columns):
                    self.add_status_message("✅ Location Point Accuracy column detected - circles will be sized accordingly")
            
            # Enable generation only if valid template detected
            if detected_type:
                self.generate_button.setEnabled(True)
                self.file_label.setText(f"✅ {filename}")
                self.file_label.setStyleSheet("color: #00ff00; font-weight: bold;")
                self.drag_drop_widget.drop_label.setText(f"📁 Ready: {filename}\n\nDrag another CSV to replace")
                
                # Enable radio button to show detection result
                if detected_type == "cell_tower":
                    self.tower_radio.setEnabled(True)
                    self.ta_radio.setEnabled(False)
                    self.gps_radio.setEnabled(False)
                elif detected_type == "timing_advance":
                    self.tower_radio.setEnabled(False)
                    self.ta_radio.setEnabled(True)
                    self.gps_radio.setEnabled(False)
                elif detected_type == "gps":
                    self.tower_radio.setEnabled(False)
                    self.ta_radio.setEnabled(False)
                    self.gps_radio.setEnabled(True)
            else:
                # Invalid format - disable generation and show error
                self.generate_button.setEnabled(False)
                self.file_label.setText(f"❌ {filename} (Invalid Format)")
                self.file_label.setStyleSheet("color: #ff6666; font-weight: bold;")
                self.drag_drop_widget.drop_label.setText(f"❌ Invalid Format: {filename}\n\nUse Templates button to download correct format")
                self.add_status_message("❌ Column headers don't match any template format")
                self.add_status_message("💡 Click 'Templates' button to download correct CSV format")
                
                # Disable all radio buttons for invalid files
                self.tower_radio.setEnabled(False)
                self.ta_radio.setEnabled(False)
                self.gps_radio.setEnabled(False)
                # Clear any previous selections
                self.tower_radio.setChecked(False)
                self.ta_radio.setChecked(False)
                self.gps_radio.setChecked(False)
                
        except Exception as e:
            # File reading error - disable generation
            self.generate_button.setEnabled(False)
            self.file_label.setText(f"❌ {filename} (Error)")
            self.file_label.setStyleSheet("color: #ff6666; font-weight: bold;")
            self.drag_drop_widget.drop_label.setText(f"❌ Error reading: {filename}\n\nCheck file format and try again")
            self.add_status_message(f"❌ Error reading CSV file: {str(e)}")
            self.add_status_message("💡 Ensure file is a valid CSV with proper headers")
            
            # Disable all radio buttons for error cases
            self.tower_radio.setEnabled(False)
            self.ta_radio.setEnabled(False)
            self.gps_radio.setEnabled(False)
            # Clear any previous selections
            self.tower_radio.setChecked(False)
            self.ta_radio.setChecked(False)
            self.gps_radio.setChecked(False)
    
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
    
    def generate_kml(self):
        """Generate KML file in background thread"""
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
        
        # Collect settings
        settings = {
            'leg_length': self.leg_length_spinbox.value(),
            'shaded_area_length': self.shaded_area_spinbox.value(),
            'azimuth_spread': self.azimuth_spinbox.value(),
            'num_points': 25,  # value for arc smoothness
            'leg_color': self.leg_color,
            'shaded_color': self.shaded_color,
            'ta_color': self.ta_color,
            'gps_color': self.gps_color,
            'gps_units': self.gps_units_combo.currentText(),
            'ta_distance_units': self.ta_distance_units_combo.currentText(),
            'default_accuracy': self.default_accuracy_spinbox.value(),
            'enable_time_animation': True,  # Always enabled
            'duration_minutes': self.duration_spinbox.value(),
            'custom_label': self.custom_label_input.text().strip() or None
        }
        
        # Start generation
        self.generate_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        self.add_status_message(f"Starting KML generation for {data_type} data...")
        
        # Create and start worker thread
        self.kml_generator = KMLGenerator(self.data_file, data_type, settings)
        self.kml_generator.progress.connect(self.progress_bar.setValue)
        self.kml_generator.finished.connect(self.on_generation_finished)
        self.kml_generator.error.connect(self.on_generation_error)
        self.kml_generator.status_message.connect(self.add_status_message)
        self.kml_generator.start()
    
    def on_generation_finished(self, kml_content):
        """Handle successful KML generation"""
        self.progress_bar.setVisible(False)
        self.generate_button.setEnabled(True)
        
        # Show file save dialog
        base_name = Path(self.data_file).stem
        
        # Use custom label for filename if provided, otherwise use base name
        custom_label = self.custom_label_input.text().strip()
        if custom_label:
            # Clean custom label for filename
            safe_label = "".join(c for c in custom_label if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_label = safe_label.replace(' ', '_')
            suggested_filename = f"{safe_label}.kml"
        else:
            suggested_filename = f"{base_name}_visualization.kml"
            
        start_dir = str(Path(self.data_file).parent / suggested_filename)
        
        output_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save KML File",
            start_dir,
            "KML Files (*.kml);;All Files (*)"
        )
        
        if output_file:
            try:
                # Save KML content to file
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(kml_content)
                
                self.add_status_message(f"✅ KML file saved successfully: {Path(output_file).name}")
                
                # Open file location and highlight file
                self.open_file_location(output_file)
            except Exception as e:
                self.add_status_message(f"❌ Error saving file: {str(e)}")
                QMessageBox.critical(
                    self,
                    "Save Error",
                    f"Failed to save KML file:\n\n{str(e)}"
                )
        else:
            self.add_status_message("⚠️ File save cancelled by user")
    
    def on_generation_error(self, error_message):
        """Handle KML generation error"""
        self.progress_bar.setVisible(False)
        self.generate_button.setEnabled(True)
        
        self.add_status_message(f"❌ Error: {error_message}")
        
        QMessageBox.critical(
            self, 
            "Error", 
            f"Failed to generate KML file:\n\n{error_message}"
        )
    
    def show_template_menu(self):
        """Show context menu with template options"""
        menu = QMenu(self)
        
        # Tower/Sector template
        tower_action = menu.addAction("📶 Tower/Sector Template")
        tower_action.triggered.connect(lambda: self.download_template("cell_tower"))
        
        # Distance from Tower template
        ta_action = menu.addAction("📏 Distance from Tower Template")
        ta_action.triggered.connect(lambda: self.download_template("timing_advance"))
        
        # Point Location template
        gps_action = menu.addAction("📌 Location Point Template")
        gps_action.triggered.connect(lambda: self.download_template("gps"))
        
        # Show menu below the button
        menu.exec(self.template_button.mapToGlobal(self.template_button.rect().bottomLeft()))
    
    def download_template(self, template_type):
        """Download a specific CSV template"""
        # Define template/sample data
        templates = {
            "cell_tower": {
                "filename": "tower_sector_template.csv",
                "headers": ["Timestamp", "Latitude", "Longitude", "Azimuth"],
                "sample_data": [
                    ["2024-01-15 14:00:00", 43.15831, -77.60938, 240],
                    ["2024-01-15 14:15:00", 43.15831, -77.60938, 240],
                    ["2024-01-15 14:30:00", 43.15400, -77.61390, 335],
                    ["2024-01-15 14:45:00", 43.15470, -77.63213, 90],
                    ["2024-01-15 15:00:00", 43.16109, -77.65102, 180],
                    ["2024-01-15 15:15:00", 43.16260, -77.67418, 180],
                    ["2024-01-15 15:30:00", 43.15831, -77.60938, 240],
                    ["2024-01-15 15:45:00", 43.15400, -77.61390, 335],
                    ["2024-01-15 16:00:00", 43.15470, -77.63213, 90],
                    ["2024-01-15 16:15:00", 43.16109, -77.65102, 180]
                ],
                "description": "Tower/Sector Data Template"
            },

            "timing_advance": {
                "filename": "timing_advance_template.csv",
                "headers": ["Timestamp", "Latitude", "Longitude", "Azimuth", "Distance"],
                "sample_data": [
                    ["2024-01-15 14:00:00", 43.15831, -77.60938, 240, 0.8],
                    ["2024-01-15 14:03:00", 43.15831, -77.60938, 240, 1.1],
                    ["2024-01-15 14:06:00", 43.15400, -77.61390, 335, 0.4],
                    ["2024-01-15 14:09:00", 43.15470, -77.63213, 90, 3.4],
                    ["2024-01-15 14:12:00", 43.16109, -77.65102, 180, 1.7],
                    ["2024-01-15 14:15:00", 43.16260, -77.67418, 180, 2.5],
                    ["2024-01-15 14:18:00", 43.15831, -77.60938, 240, 4.2],
                    ["2024-01-15 14:21:00", 43.15400, -77.61390, 335, 1.3],
                    ["2024-01-15 14:24:00", 43.15470, -77.63213, 90, 0.5],
                    ["2024-01-15 14:27:00", 43.16109, -77.65102, 180, 1.8]
                ],
                "description": "Distance from Tower Data Template"
            },

            "gps": {
                "filename": "location_point_template.csv",
                "headers": ["Timestamp", "Latitude", "Longitude", "Accuracy"],
                "sample_data": [
                    ["2024-01-15 14:00:00", 43.156622, -77.608895, 250],
                    ["2024-01-15 14:01:00", 43.157830, -77.605310, 200],
                    ["2024-01-15 14:02:00", 43.158941, -77.601745, 150],
                    ["2024-01-15 14:03:00", 43.159756, -77.594527, 300],
                    ["2024-01-15 14:04:00", 43.161422, -77.591803, 200],
                    ["2024-01-15 14:05:00", 43.163650, -77.590300, 150],
                    ["2024-01-15 14:06:00", 43.166050, -77.589700, 100],
                    ["2024-01-15 14:07:00", 43.168453, -77.589232, 500],
                    ["2024-01-15 14:08:00", 43.167950, -77.589800, 200],
                    ["2024-01-15 14:09:00", 43.167541, -77.590212, 150]
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
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if output_file:
            try:
                # Create DataFrame with template data
                df = pd.DataFrame(template['sample_data'], columns=template['headers'])
                
                # Save to CSV
                df.to_csv(output_file, index=False)
                
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
                    f"• Sample data rows to show the expected format\n\n"
                    f"Carefully replace the sample data with your own data in Excel or another program and save the file as either a CSV or XLSX. You can also load this sample file directly to see how the visualizer works."
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
