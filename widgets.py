"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QTableWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent


class DragDropWidget(QFrame):
    """Custom widget that accepts drag and drop for CSV and Excel files"""
    file_dropped = pyqtSignal(str)  # Signal emitted when file is dropped
    
    def __init__(self, compact=False):
        super().__init__()
        self.setProperty("compact", compact)
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(2)
        self.setMinimumHeight(54 if compact else 80)
        if compact:
            self.setMaximumHeight(62)
        
        # Create layout for drop zone
        layout = QHBoxLayout(self) if compact else QVBoxLayout(self)
        if compact:
            layout.setContentsMargins(14, 7, 8, 7)
            layout.setSpacing(12)
        
        label_text = (
            "📁 Drop CSV or Excel marker list here"
            if compact else
            "📁 Drag & Drop CSV or Excel File Here\n\n— OR —"
        )
        self.drop_label = QLabel(label_text)
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setStyleSheet("""
            QLabel {
                color: #888888;
                font-size: 14px;
                background: transparent;
                padding: 0px;
            }
        """)
        
        self.browse_button = QPushButton("Browse for File")
        self.browse_button.setMaximumWidth(200)
        
        if compact:
            self.or_label = QLabel("— OR —")
            self.or_label.setStyleSheet(
                "color: #aaaaaa; background: transparent;"
            )
            layout.addStretch()
            layout.addWidget(self.drop_label)
            layout.addWidget(self.or_label)
            layout.addWidget(self.browse_button)
            layout.addStretch()
        else:
            self.or_label = None
            layout.addWidget(self.drop_label)
            layout.addSpacing(12)  # Add space above button for symmetry
            layout.addWidget(
                self.browse_button,
                alignment=Qt.AlignmentFlag.AlignCenter,
            )
        
        self.setStyleSheet("""
            DragDropWidget {
                border: 2px dashed #555555;
                border-radius: 8px;
                background-color: #1e1e1e;
                padding: 20px;
            }
            DragDropWidget[dragActive="true"] {
                background-color: #1a3a5c;
            }
            DragDropWidget[compact="true"] {
                border-radius: 6px;
                padding: 0px;
            }
        """)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter event"""
        if event.mimeData().hasUrls():
            # Check if any of the URLs point to CSV or Excel files
            urls = event.mimeData().urls()
            for url in urls:
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    if file_path.lower().endswith(('.csv', '.xls', '.xlsx')):
                        event.acceptProposedAction()
                        self.setProperty("dragActive", True)
                        self.style().unpolish(self)
                        self.style().polish(self)
                        self.update()
                        return
        event.ignore()

    def dragLeaveEvent(self, event):
        """Handle drag leave event"""
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def dropEvent(self, event: QDropEvent):
        """Handle drop event"""
        self.setProperty("dragActive", False)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            for url in urls:
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    if file_path.lower().endswith(('.csv', '.xls', '.xlsx')):
                        self.file_dropped.emit(file_path)
                        event.acceptProposedAction()
                        return
        event.ignore()


class MarkerTableWidget(QTableWidget):
    """Keep marker headers and coordinate values readable as the window resizes."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_marker_columns()

    def resize_marker_columns(self):
        if self.columnCount() < 5:
            return

        available_width = max(self.viewport().width(), 1)
        color_width = 92
        remove_width = 40
        coordinate_minimum = max(
            self.fontMetrics().horizontalAdvance("-123.123456789") + 20,
            118,
        )
        label_target = int(available_width * 0.42)
        label_width = max(
            min(
                label_target,
                available_width
                - (2 * coordinate_minimum)
                - color_width
                - remove_width,
            ),
            120,
        )
        coordinate_width = max(
            (available_width - label_width - color_width - remove_width) // 2,
            coordinate_minimum,
        )
        longitude_width = max(
            available_width - label_width - color_width
            - remove_width - coordinate_width,
            coordinate_minimum,
        )

        self.setColumnWidth(0, label_width)
        self.setColumnWidth(1, coordinate_width)
        self.setColumnWidth(2, longitude_width)
        self.setColumnWidth(3, color_width)
        self.setColumnWidth(4, remove_width)
