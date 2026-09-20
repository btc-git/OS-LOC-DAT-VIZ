"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QWidget, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from license_dialog import LicenseDialog
from version import APP_VERSION

# License Label
class LicenseClickableLabel(QLabel):
    clicked = pyqtSignal()
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

class DisclaimerDialog(QDialog):


    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Important Disclaimers & Usage Information")
        self.setModal(True)
        self.setMinimumSize(600, 500)
        self.setMaximumSize(800, 700)
        self.resize(700, 600)

        layout = QVBoxLayout(self)

        # Header
        header_label = QLabel("Open Source Location Data Visualizer")
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_font = QFont()
        header_font.setPointSize(18)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setStyleSheet("color: #0078d4; margin: 10px;")
        layout.addWidget(header_label)

        # Subtitle
        subtitle_label = QLabel("<span style='font-size:18px;'></span> <span style='vertical-align:middle;'>Important Disclaimers & Usage Information</span> <span style='font-size:18px;'></span>")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_font = QFont()
        subtitle_font.setPointSize(12)
        subtitle_label.setFont(subtitle_font)
        subtitle_label.setStyleSheet("color: #cccccc; margin-bottom: 15px;")
        layout.addWidget(subtitle_label)

        # Scrollable content area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)

        # Disclaimer
        disclaimer_text = f"""
<div style='font-family: "Segoe UI", Arial, sans-serif; line-height: 1.6; padding: 15px;'>

<h3 style='color: #ff6b6b; margin-top: 0;'>🔴 CRITICAL DISCLAIMER</h3>
<ul>
    <li><strong>Preliminary Visualization Only:</strong> This application is a triage tool for quick, initial review and visualization of location data. <span style='color: #ff6b6b;'><strong>All data and mapping must be independently verified by qualified experts before any formal or legal use.</strong></span></li>
    <li><strong>No Coverage Estimations:</strong> All shaded areas, wedges, and circles are visual representations only - not coverage depictions. The application transforms source data into preliminary KML visualizations using user-selected settings. It does not determine device location or RF coverage. All source values, assumptions, conversions, and generated geometry must be independently verified.</li>
</ul>

<h3 style='color: #00b894; margin-top: 25px;'>📝 Usage Overview</h3>
<ol>
    <li>Drag and drop a CSV or Excel file into the program, or use the <strong>Browse for File</strong> button. Standard template files are recognized automatically.</li>
    <li>If the headers do not match a standard template, the mapping wizard opens automatically. Select the worksheet and header row, choose the record type, and verify each suggested column mapping.</li>
    <li>Review the timezone, slash/dash date order, units, visualization settings, and optional label.</li>
    <li>Click <strong>Generate</strong> to create same-named KML, GeoJSON, and TXT generation-log files.</li>
    <li>Review the log’s settings, hashes, row outcomes, and warnings before opening the KML in Google Earth Pro or using the GeoJSON in another compatible GIS application.</li>
</ol>

<h3 style='color: #3dc1d3; margin-top: 25px;'>🎨 Visualization Details</h3>
<ul>
    <li>If your data includes tower and sector information, the tool will draw a wedge shape to show the general direction. If no azimuth is provided, it will draw a circle. The default wedge is set to a 120° angle and a 1 mile shaded area, but this is for visualization only and does not reflect coverage.</li>
    <li>If your data includes a distance from the tower, the tool will draw a band at that distance with configurable inner and outer thickness. This depicts the source-reported or inferred distance and any user-selected band extensions. It does not establish that the device was within the displayed area or at an exact distance from the tower.</li>
    <li>For location point data, the tool will draw a circle to represent the point and its accuracy, using either the provided accuracy or a default value of 100 meters.</li>
</ul>

<h3 style='color: #feca57; margin-top: 25px;'>🛠️ Technical Guidance</h3>
<ul>
    <li><strong>Data Format & Units:</strong> Be careful when transferring data into the templates.</li>
    <li><strong>Supported Timestamp Formats:</strong> The application supports <strong>18+ timestamp formats</strong>, including:
        <ul>
            <li><strong>ISO:</strong> 2025-01-15T14:30:00, 2025-01-15 14:30, 2025/02/11 11:06:07</li>
            <li><strong>US (4-digit year):</strong> 01/15/2025 2:30 PM, 01/15/2025 2:30, 08/01/2015 22:14:13</li>
            <li><strong>US (2-digit year):</strong> 07/30/24 13:00:20 (auto-converts: 00–30 → 2000–2030, 31–99 → 1931–1999)</li>
            <li><strong>European:</strong> 15.01.2025 14:30:00, 15.01.2025 14:30</li>
            <li><strong>Time-only:</strong> 14:30:00, 2:30 PM (uses today's date)</li>
            <li><strong>Advanced:</strong> Excel serial dates (45696.7637037037), timestamps with explicit timezone offsets converted to UTC, separate Date and Time columns, selectable slash/dash date order, milliseconds auto-handled</li>
        </ul>
    </li>
    <li><strong>Timezone Review:</strong> Named timezones apply historical daylight-saving rules. Ambiguous or nonexistent transition times are omitted and identified in the status console rather than assigned an assumed instant.</li>
    <li>Distances and accuracy values can be provided in configurable units (Meters, Feet, Miles, or Kilometers). Azimuth in degrees (0°=N, 90°=E, 180°=S, 270°=W). Coordinates in decimal degrees (e.g., 40.724756, -74.222508).</li>
    <li><strong>Viewing Outputs:</strong> Import generated KML files into Google Earth Pro or compatible GIS software, or use the paired GeoJSON in GeoLibre/MapLibre workflows. Use the available timeline controls to view data over time.</li>
</ul>

<h3 style='color: #4ecdc4; margin-top: 25px;'>🔒 Privacy & Security</h3>
<ul>
    <li>Location-data processing and export run locally; the application does not upload source or output files.</li>
    <li>Generated KML, GeoJSON, and TXT logs can contain sensitive location information. Opening links or outputs in other applications is subject to those applications’ behavior.</li>
</ul>

<h3 style='color: #feca57; margin-top: 25px;'>Troubleshooting</h3>
<ul>
    <li>If timestamps are not recognized, make sure they match one of the supported formats listed above.</li>
    <li>If you are working with a large dataset, this program may run slowly and the KML file may struggle to load in Google Earth Pro. Try processing a smaller subset of your data if you encounter problems.</li>
</ul>

<p style='text-align: center; margin-top: 30px; color: #666666; font-style: italic;'>
Version {APP_VERSION}<br/>
Open Source Location Data Visualization Tool<br/>
<br/>
<strong>📜 Licenses &amp; Notices:</strong> <a href="license://show" style="color:#4ecdc4; text-decoration:underline; cursor:pointer;">View license texts</a><br/>
OS-LOC-DAT-VIZ is licensed under GNU GPL v3.0 and packages GeoLibre 3.0.0 under the MIT License.<br/>
<br/>
<span style='color: #4ecdc4; font-size: 11pt;'>This is an open source project. Found a bug or have a suggestion? <br>Contribute or open an issue at <a href="https://github.com/btc-git/OS-LOC-DAT-VIZ" style="color:#4ecdc4; text-decoration:underline;">GitHub</a>.</span>
</p>

</div>
                """

        disclaimer_label = QLabel(disclaimer_text)
        disclaimer_label.setWordWrap(True)
        disclaimer_label.setTextFormat(Qt.TextFormat.RichText)
        disclaimer_label.setStyleSheet("""
            QLabel {
                background-color: #1e1e1e;
                border: 1px solid #444444;
                border-radius: 8px;
                padding: 0px;
                margin: 0px;
            }
        """)
        disclaimer_label.setOpenExternalLinks(False)
        disclaimer_label.linkActivated.connect(self.handle_license_link)
        content_layout.addWidget(disclaimer_label)

        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)

        # Buttons
        button_layout = QHBoxLayout()
        self.understand_button = QPushButton("Close")
        self.understand_button.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                font-weight: bold;
                padding: 12px 24px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        self.understand_button.clicked.connect(self.accept)

        button_layout.addStretch()
        button_layout.addWidget(self.understand_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

    def handle_license_link(self, link):
        if link == "license://show":
            self.show_license_dialog()
        elif link.startswith("http://") or link.startswith("https://"):
            import webbrowser
            webbrowser.open(link)

    def show_license_dialog(self):
        self.license_window = LicenseDialog(self)
        self.license_window.show()

        # Dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QScrollArea {
                border: none;
                background-color: #2b2b2b;
            }
            QScrollBar:vertical {
                background-color: #404040;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #606060;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #707070;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator::unchecked {
                border: 2px solid #555555;
                border-radius: 3px;
                background-color: #2b2b2b;
            }
            QCheckBox::indicator::checked {
                border: 2px solid #0078d4;
                border-radius: 3px;
                background-color: #0078d4;
                image: url(data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='white'%3E%3Cpath d='M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z'/%3E%3C/svg%3E);
            }
        """)
