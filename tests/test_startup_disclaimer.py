"""
Open Source Location Data Visualizer - github.com/btc-git/OS-LOC-DAT-VIZ
Licensed under the GNU General Public License v3.0 - see LICENSE file for details
"""

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from dialogs import DisclaimerDialog
from main_window import MainWindow


class StartupDisclaimerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_is_visible_during_modal_disclaimer(self):
        original_exec = DisclaimerDialog.exec
        for dismissal in ("button", "window"):
            with self.subTest(dismissal=dismissal):
                observations = []

                def execute_dialog(dialog):
                    def dismiss_dialog():
                        observations.append((
                            dialog.parentWidget().isVisible(),
                            dialog.isVisible(),
                            dialog.isModal(),
                            self.app.activeModalWidget() is dialog,
                        ))
                        if dismissal == "button":
                            dialog.understand_button.click()
                        else:
                            dialog.close()

                    QTimer.singleShot(0, dismiss_dialog)
                    return original_exec(dialog)

                dialog_exec = Mock(side_effect=execute_dialog)
                with patch.object(
                    DisclaimerDialog, "exec",
                    new=lambda dialog: dialog_exec(dialog),
                ):
                    window = MainWindow()
                    try:
                        dialog_exec.assert_not_called()
                        window.show()
                        self.app.processEvents()

                        self.assertEqual([(True, True, True, True)], observations)
                        dialog_exec.assert_called_once()
                        self.assertTrue(window.isVisible())
                        self.assertIsNone(self.app.activeModalWidget())

                        window.hide()
                        window.show()
                        self.app.processEvents()
                        dialog_exec.assert_called_once()

                        window.info_button.click()
                        self.assertEqual(2, dialog_exec.call_count)
                        self.assertEqual(
                            [(True, True, True, True)] * 2, observations
                        )
                        self.assertTrue(window.isVisible())
                    finally:
                        window.close()
                        window.deleteLater()
                        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
