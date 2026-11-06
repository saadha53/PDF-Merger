import os
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from gui.main_window import MainWindow
from utils.resource_utils import resource_path


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("PDFMerger")
    app.setApplicationName("PDF Merger")

    window = MainWindow()

    icon_ico = resource_path(os.path.join("gui", "assets", "app_icon.ico"))
    if os.path.exists(icon_ico):
        window.setWindowIcon(QIcon(icon_ico))

    window.show()
    if "--smoke-test" in sys.argv:
        QTimer.singleShot(250, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
