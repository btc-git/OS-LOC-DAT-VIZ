"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import sys
import os
from PyQt6.QtWidgets import QApplication
from main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    
    # Set application properties
    app.setApplicationName("Open Source Location Data Visualizer")
    app.setApplicationVersion("1.0")
    app.setOrganizationName("OpenSource")
    
    # Create and show main window
    window = MainWindow()
    
    # Set the application icon for taskbar
    icon = window.create_pushpin_icon()
    app.setWindowIcon(icon)
    
    # For Windows taskbar grouping (helps with custom icon display)
    if os.name == 'nt':  # Windows
        try:
            import ctypes
            myappid = 'opensource.locationvisualizer.1.0'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except:
            pass
    
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
