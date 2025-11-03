"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea, QWidget
from PyQt6.QtCore import Qt
from pathlib import Path

class LicenseDialog(QDialog):
    """Dialog to display the LICENSE file contents"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("License - GNU GPL v3.0")
        self.setMinimumSize(600, 500)
        self.setModal(True)


        layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # License label
        license_text = self._read_license()
        license_label = QLabel(license_text)
        license_label.setWordWrap(True)
        license_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        license_label.setStyleSheet("""
            QLabel {
                background-color: #1e1e1e;
                color: #cccccc;
                border: 1px solid #444444;
                border-radius: 8px;
                padding: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 10pt;
            }
        """)
        scroll_area.setWidget(license_label)
        layout.addWidget(scroll_area)

        # Close button
        from PyQt6.QtWidgets import QHBoxLayout, QPushButton
        button_layout = QHBoxLayout()
        close_button = QPushButton("Close")
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                font-weight: bold;
                padding: 10px 24px;
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
        close_button.clicked.connect(self.accept)
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

    def _read_license(self):
        # Try to find LICENSE file in the same directory as the executable or script
        possible_paths = [
            Path(__file__).parent / "LICENSE",
            Path(__file__).parent.parent / "LICENSE"
        ]
        for path in possible_paths:
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8")
                except Exception:
                    continue
        return "License file not found. Please see the repository for details."
