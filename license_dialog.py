"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QScrollArea
from PyQt6.QtCore import Qt
from pathlib import Path
import sys

class LicenseDialog(QDialog):
    """Display application and bundled third-party license notices."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Licenses & Third-Party Notices")
        self.setMinimumSize(600, 500)
        self.setModal(True)


        layout = QVBoxLayout(self)

        notice_label = QLabel(
            "OS-LOC-DAT-VIZ is licensed under GNU GPL v3.0. This distribution "
            "also packages the unmodified GeoLibre Desktop 3.0.0 application "
            "for viewer functionality; GeoLibre is separately licensed under "
            "the MIT License. The project license, dependency inventory, and "
            "license files included in this build follow."
        )
        notice_label.setWordWrap(True)
        notice_label.setStyleSheet("color: #cccccc; padding: 4px 2px 8px 2px;")
        layout.addWidget(notice_label)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # License label
        license_text = self._read_license()
        self.license_label = QLabel(license_text)
        self.license_label.setTextFormat(Qt.TextFormat.PlainText)
        self.license_label.setWordWrap(True)
        self.license_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.license_label.setStyleSheet("""
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
        scroll_area.setWidget(self.license_label)
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

    @staticmethod
    def _resource_roots():
        return [
            Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)),
            Path(__file__).resolve().parent,
            Path(__file__).resolve().parent.parent,
        ]

    @classmethod
    def _read_resource(cls, relative_path):
        for root in cls._resource_roots():
            path = root / relative_path
            if path.is_file():
                try:
                    return path.read_text(encoding="utf-8")
                except OSError:
                    continue
        return f"License file not found: {relative_path}"

    @classmethod
    def _read_resource_directory(cls, relative_path):
        for root in cls._resource_roots():
            directory = root / relative_path
            if not directory.is_dir():
                continue
            sections = []
            for path in sorted(
                candidate for candidate in directory.rglob('*')
                if candidate.is_file()
            ):
                try:
                    text = path.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    continue
                sections.append(
                    f"--- {path.relative_to(directory).as_posix()} ---\n\n"
                    f"{text.rstrip()}"
                )
            if sections:
                return "\n\n".join(sections)
        return ""

    def _read_license(self):
        project_license = self._read_resource("LICENSE")
        third_party_notices = self._read_resource("THIRD_PARTY_NOTICES.md")
        geolibre_license = self._read_resource(
            Path("GeoLibre-Viewer") / "LICENSE-GeoLibre.txt"
        )
        packaged_dependency_licenses = self._read_resource_directory(
            "Third-Party-Licenses"
        )
        separator = "=" * 72
        sections = [
            "OS-LOC-DAT-VIZ - GNU GPL v3.0\n"
            "https://github.com/btc-git/OS-LOC-DAT-VIZ\n\n"
            f"{project_license.rstrip()}",
            "THIRD-PARTY DEPENDENCY INVENTORY\n\n"
            f"{third_party_notices.rstrip()}",
            "BUNDLED THIRD-PARTY SOFTWARE\n\n"
            f"{geolibre_license.rstrip()}",
        ]
        if packaged_dependency_licenses:
            sections.append(
                "PACKAGED DEPENDENCY LICENSE FILES\n\n"
                f"{packaged_dependency_licenses}"
            )
        return f"\n\n{separator}\n\n".join(sections) + "\n"
