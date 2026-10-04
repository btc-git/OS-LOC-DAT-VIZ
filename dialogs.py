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
    <li><strong>Preliminary Visualization Only:</strong> This application is for quick, initial review and mapping of location data. <span style='color: #ff6b6b;'><strong>All data and mapping must be independently verified by qualified experts before any formal or legal use.</strong></span></li>
    <li><strong>No RF Coverage Estimates:</strong> All shaded areas, wedges, and circles are visual representations only - they do not show radio signal coverage. The application transforms source data into KML and GeoJSON visualizations using your selected settings. It does not calculate device locations or radio frequency (RF) coverage. All source values, assumptions, conversions, and shapes drawn on the map must be independently verified.</li>
</ul>

<h3 style='color: #00b894; margin-top: 25px;'>📝 Usage Overview</h3>
<ol>
    <li>Drag and drop a CSV, XLS, or XLSX file into the program, or click the <strong>Browse for File</strong> button. Standard CSV/XLSX template files are recognized automatically; files in the older XLS format open the mapping wizard.</li>
    <li>If the column names do not match one of the included basic templates, the <strong>Import Original Records</strong> mapping wizard opens automatically. Select the worksheet (if the Excel file has more than one) and the row containing the column names. Choose the record type and check that each source column is matched to the correct field. For Cell Site/Sector and Distance from Cell Site data, you can optionally match the records to a separate cell site list using site/node and sector/cell IDs to obtain coordinates and antenna direction (azimuth).</li>
    <li>You can limit the import to a date/time range to speed up processing. By default, the full selected days are included unless <strong>Use exact times</strong> is enabled. <strong>Check Matching Rows</strong> shows how many records match the date/time range and have valid mapped coordinates before import.</li>
    <li>Review the timezone, date order (month or day first), units, visualization settings, and data label. Add or import additional points of interest as markers on the <strong>Markers</strong> tab when needed.</li>
    <li>Click <strong>Process</strong> to generate a KML, GeoJSON, and TXT log file, or <strong>Process and Open in Viewer</strong> to generate, save, and then open the GeoJSON in the included GeoLibre viewer.</li>
    <li>Review the TXT log for settings, file hashes (digital fingerprints), counts of included and skipped records, and warnings. Use <strong>Open Viewer</strong> and then <strong>Load GeoJSON</strong> to review previously generated GeoJSON mapping files. Load multiple GeoJSON files to compare data sets. Generated KML files can be opened in Google Earth Pro. GeoJSON is recommended for the included GeoLibre viewer. <strong>Process and Open in Viewer</strong> also saves a <strong>.geolibre</strong> project; keep it with its GeoJSON file so the viewer can reopen the data.</li>
</ol>

<h3 style='color: #3dc1d3; margin-top: 25px;'>🎨 Visualization Details</h3>
<ul>
    <li>If a site location and antenna direction (azimuth) are provided, the tool draws a wedge from the site with the middle of the wedge pointing in that direction. If no azimuth is provided, the tool draws a circle around the site. By default, the shaded wedge is 120° wide and extends 1 mile from the site. These dimensions are visualization settings only and do not represent RF coverage.</li>
    <li>If your data includes a distance from the cell site, the tool displays the reported distance as a line or shaded band using the configured inner and outer band settings. If distance is missing, no distance band is drawn. It does not establish that the device was within the displayed area or at an exact distance from the cell site.</li>
    <li>For Location Point data, a positive accuracy value draws an accuracy circle around the point. If accuracy is missing, the configured default radius is used (initially 0). A zero default means no accuracy radius is assumed; it does not mean the location is exact. The point remains visible without a circle. A source accuracy value of zero also means unknown accuracy, not an exact location, and draws no circle. Invalid accuracy produces a point without an accuracy circle, even when a positive default is configured. A positive default is your visualization assumption, not measured accuracy.</li>
    <li>Cell Site/Sector and Distance from Cell Site processing includes a separate static <strong>Reference Cell Sites</strong> record set within the mapping files. When a separate cell site list is not provided, the mapping files show unique cell sites used by the records. When a separate cell site list is provided, the mapping files include the reference cell sites within the configured radius (default of 25 miles). Clicking the reference cell site marker on the map shows contributing source rows and available site IDs.</li>
    <li>User Markers are exported as a separate static record set with individual colors, labels, coordinates, and independent controls. They apply only to the current source record set being processed.</li>
</ul>

<h3 style='color: #feca57; margin-top: 25px;'>🛠️ Technical Guidance</h3>
<ul>
    <li><strong>Data Format &amp; Units:</strong> Verify mapped coordinates, record type, distance and accuracy units, and suggested columns rather than assuming automatic detection is correct.</li>
    <li><strong>Supported Date and Time Formats:</strong> The application supports many common date and time formats, including:
        <ul>
            <li><strong>ISO:</strong> 2025-01-15T14:30:00, 2025-01-15 14:30, 2025/02/11 11:06:07</li>
            <li><strong>US (4-digit year):</strong> 01/15/2025 2:30 PM, 01/15/2025 2:30, 08/01/2015 22:14:13</li>
            <li><strong>US (2-digit year):</strong> 07/30/24 13:00:20 (auto-converts: 00–30 → 2000–2030, 31–99 → 1931–1999)</li>
            <li><strong>European:</strong> 15.01.2025 14:30:00, 15.01.2025 14:30</li>
            <li><strong>Time-only:</strong> 14:30:00, 2:30 PM (uses today's date)</li>
            <li><strong>Other date and time options:</strong>
                <ul>
                    <li><strong>Excel dates:</strong> The app can read dates and times that Excel stores as numbers, even if they do not look like a normal date.</li>
                    <li><strong>Times with a timezone:</strong> If a time includes a timezone offset, such as -05:00, the app uses that offset to convert it to UTC.</li>
                    <li><strong>Separate columns:</strong> Dates and times can be in separate columns, such as a Date column and a Time column.</li>
                    <li><strong>Month or day first:</strong> For dates with slashes or dashes, choose whether the month or day comes first. For example, 03/04/2025 could mean March 4 or April 3.</li>
                    <li><strong>Parts of a second:</strong> For dates and times written as text, digits after the seconds are ignored. For example, 14:30:00.123 is treated as 14:30:00.</li>
                    <li><strong>Double-check assumed dates:</strong> A time without a date uses today's date. A two-digit year is interpreted as shown above. Dates, timestamps, and timezone conversion can be tricky, so carefully check the input data and resulting map. Do not assume the tool has interpreted them correctly without verification.</li>
                </ul>
            </li>
        </ul>
    </li>
    <li><strong>Timezone Review:</strong> If a timestamp already contains a timezone offset, such as -05:00, the app uses that offset instead of the configured source timezone. Named timezones automatically apply historical daylight-saving rules. Choose a display timezone to show dates and times in that timezone. Any date/time range you enter to limit the import is also read in that timezone. Choose <strong>No Change</strong> to keep dates and times in the source timezone. When clocks change for daylight saving, some local times happen twice or are skipped entirely. If the app cannot tell which time a record means, it keeps the usable location without a date or time and reports the problem instead of guessing. A date/time range filter excludes these records.</li>
    <li><strong>Missing or unreadable dates and times:</strong> For all record types, records with usable location information are kept on the map even if their date and time are missing, unreadable, or uncertain. They are labeled <strong>date/time unavailable</strong>, have no timeline time, and are counted in warnings and the TXT log. If you limit the import to a date/time range, these records are excluded because the app cannot confirm that they fall within your selected range.</li>
    <li>Distances and accuracy values can be provided in configurable units (Meters, Feet, Miles, or Kilometers). Azimuth is measured in degrees (0°=N, 90°=E, 180°=S, 270°=W). Coordinates are provided in decimal degrees (e.g., 40.724756, -74.222508).</li>
    <li><strong>Included Viewer:</strong> GeoLibre provides record-set and individual-event controls, <strong>From/Through</strong> date and time filtering (including both endpoints), timeline playback, labels, and event details. Records open as hidden by default; enable individual events or use <strong>Show All</strong> for the entire record set. Use <strong>Focus Set</strong> or <strong>Zoom to Event</strong> to jump to the event area on the map. Reference cell sites and markers have separate controls and remain static during timeline playback and date filtering.</li>
</ul>

<h3 style='color: #4ecdc4; margin-top: 25px;'>🔒 Privacy & Security</h3>
<ul>
    <li>Location data is processed locally, and the application does not upload source or output files. The viewer may still contact online map services.</li>
    <li>Generated KML, GeoJSON, TXT logs, and .geolibre projects can contain sensitive location information or file paths and should be treated with the same level of confidentiality as the source files themselves. Be cautious when loading map files into online viewers or services as that may expose sensitive information externally.</li>
    <li>The included viewer's default base map uses <strong>OpenFreeMap</strong> and requires a network connection. Requests for map tiles (pieces of the background map) send ordinary request information, including your IP address and the map area being requested, to that service.</li>
</ul>

<h3 style='color: #feca57; margin-top: 25px;'>Troubleshooting</h3>
<ul>
    <li><strong>Slow viewing or large datasets:</strong> If a KML is slow to load or navigate in Google Earth Pro, try opening the <strong>GeoJSON output in the included GeoLibre viewer</strong>. GeoJSON is optimized for this data mapping workflow and may provide a smoother viewing experience, but performance still depends on dataset size, geometry, and computer hardware. Limit the imported date/time range or process smaller subsets if generation or viewing remains slow.</li>
    <li><strong>If the data loaded but nothing is visible in the Viewer:</strong> GeoLibre opens with all records hidden. Enable individual events or click Show All to display the entire record set, check any active From/Through filter, then click Focus Set. Reference Cell Site markers and your own markers can be toggled on and off separately.</li>
    <li><strong>Viewer will not start:</strong> Close any other running GeoLibre window before launching the included viewer. GeoLibre allows one running instance per Windows session. Review the status console or error dialog if launch still fails.</li>
    <li><strong>Missing records or unexpected times:</strong> Check the source and display timezones, slash/dash date order, timestamp mappings, coordinate validity, cell site list mapping, and active import filter. Review summarized warnings and the TXT log’s row outcomes rather than assuming every source row was exported correctly.</li>
</ul>

<p style='text-align: center; margin-top: 30px; color: #666666; font-style: italic;'>
Version {APP_VERSION}<br/>
Open Source Location Data Visualization Tool<br/>
<br/>
<strong>📜 Licenses &amp; Notices:</strong> <a href="license://show" style="color:#4ecdc4; text-decoration:underline; cursor:pointer;">View license texts</a><br/>
OS-LOC-DAT-VIZ is licensed under GNU GPL v3.0 and includes GeoLibre 3.0.0 under the MIT License.<br/>
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
