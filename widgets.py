"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent


class DragDropWidget(QFrame):
    """Custom widget that accepts drag and drop for CSV and Excel files"""
    file_dropped = pyqtSignal(str)  # Signal emitted when file is dropped
    
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(2)
        self.setMinimumHeight(80)
        
        # Create layout for drop zone
        layout = QVBoxLayout(self)
        
        self.drop_label = QLabel("📁 Drag & Drop CSV or Excel File Here\n\n— OR —")
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
        
        layout.addWidget(self.drop_label)
        layout.addSpacing(12)  # Add space above button for symmetry
        layout.addWidget(self.browse_button, alignment=Qt.AlignmentFlag.AlignCenter)
        
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
        """)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter event"""
        if event.mimeData().hasUrls():
            # Check if any of the URLs point to CSV or Excel files
            urls = event.mimeData().urls()
            for url in urls:
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    if file_path.lower().endswith(('.csv', '.xlsx')):
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
                    if file_path.lower().endswith(('.csv', '.xlsx')):
                        self.file_dropped.emit(file_path)
                        event.acceptProposedAction()
                        return
        event.ignore()
