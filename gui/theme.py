from string import Template

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPalette, QPen
from PyQt6.QtWidgets import QCheckBox, QStyle, QStyleOptionButton


COLORS = {
    "desk": "#f1eeea",
    "paper": "#fdfbf8",
    "surface": "#f7f4f0",
    "hover": "#eee8e2",
    "ink": "#26201d",
    "muted": "#625751",
    "rule": "#ded6cf",
    "edge": "#bfb2a8",
    "control": "#8f8076",
    "accent": "#9c4131",
    "focus_on_ink": "#e2907b",
    "selection": "#f2ddd5",
    "dark_hover": "#403632",
    "disabled": "#776b63",
    "error": "#962d27",
    "success": "#285c46",
    "transparent": "transparent",
}
FONT = "Segoe UI"

STYLESHEET = Template("""
/* Hallmark v2.0.0 | Coral | full redesign | app screen | modern-minimal
   The document queue leads. Save settings stay beside it at every window size.
   Native Qt adaptation: system type, solid paper surfaces and instant feedback. */
QWidget {
    font-family: "$font"; font-size: 13px; color: $ink;
}
QMainWindow, QDialog, QMessageBox { background: $desk; }
QLabel { background: $transparent; }
QLabel#PageTitle { font-size: 32px; font-weight: 700; }
QLabel#SectionTitle { font-size: 18px; font-weight: 600; }
QLabel#EmptyTitle { font-size: 20px; font-weight: 600; }
QLabel#Muted, QLabel#PrivacyLabel { color: $muted; }
QLabel#PrivacyLabel { font-size: 12px; }
QLabel#TotalPagesLabel { font-size: 15px; font-weight: 600; }
QFrame#Rule { background: $rule; }
QFrame#OutputPanel { background: $surface; border: 1px solid $rule; border-radius: 8px; }

QTableWidget {
    background: $paper; border: 1px solid $rule; border-radius: 8px;
    selection-background-color: $selection; selection-color: $ink;
}
QTableWidget:focus { border-color: $accent; }
QTableWidget::item { padding: 0 8px; border-bottom: 1px solid $rule; }
QTableWidget::item:selected { background: $selection; color: $ink; }
QTableWidget::item:focus { border-bottom-color: $accent; }
QHeaderView { background: $surface; }
QHeaderView::section {
    background: $surface; color: $muted; border: none; border-bottom: 1px solid $rule;
    padding: 10px 8px; font-weight: 600;
}
QHeaderView::section:hover { background: $hover; color: $ink; }

QToolButton, QPushButton {
    background: $paper; border: 1px solid $edge; border-radius: 6px;
    min-height: 20px; padding: 7px 8px; font-weight: 500;
}
QToolButton:hover, QPushButton:hover { background: $hover; border-color: $control; }
QToolButton:pressed, QPushButton:pressed { background: $selection; }
QToolButton:disabled, QPushButton:disabled { color: $disabled; background: $surface; border-color: $rule; }
QToolButton#QuietButton { background: $transparent; border-color: $transparent; }
QToolButton#QuietButton:hover { background: $hover; }
QToolButton#QuietButton:pressed { background: $selection; }
QToolButton#AddButton { font-weight: 600; padding-left: 15px; padding-right: 15px; }
QPushButton#MergeButton, QDialogButtonBox QPushButton:default {
    background: $ink; border: 2px solid $ink; color: $paper;
}
QPushButton#MergeButton { min-height: 24px; font-weight: 600; }
QDialogButtonBox QPushButton { min-width: 72px; }
QPushButton#MergeButton:hover, QDialogButtonBox QPushButton:default:hover {
    background: $dark_hover;
}
QPushButton#MergeButton:pressed, QDialogButtonBox QPushButton:default:pressed {
    background: $accent;
}
QPushButton#MergeButton:disabled, QDialogButtonBox QPushButton:default:disabled {
    color: $disabled; background: $hover; border-color: $rule;
}
QLineEdit {
    background: $paper; border: 1px solid $control; border-radius: 6px;
    padding: 6px 9px; selection-background-color: $selection; selection-color: $ink;
}
QLineEdit:disabled { background: $surface; color: $disabled; }
QToolButton:focus, QToolButton#QuietButton:focus, QPushButton:focus, QLineEdit:focus {
    border-color: $accent;
}
QPushButton#MergeButton:focus, QDialogButtonBox QPushButton:default:focus {
    border-color: $focus_on_ink;
}
QCheckBox { spacing: 7px; padding: 5px 3px; border: 1px solid $transparent; border-radius: 4px; }
QCheckBox:focus { border-color: $accent; }
QCheckBox:disabled { color: $disabled; }
QCheckBox::indicator {
    width: 14px; height: 14px; border: 1px solid $control; border-radius: 4px; background: $paper;
}
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QCheckBox::indicator:disabled { background: $hover; border-color: $edge; }
QCheckBox::indicator:checked:disabled { background: $disabled; border-color: $disabled; }
QStatusBar { background: $surface; color: $muted; border-top: 1px solid $rule; }
QStatusBar::item { border: 0; }
QToolTip { background: $ink; color: $paper; border: 1px solid $ink; padding: 5px; }
QProgressBar {
    background: $paper; border: 1px solid $edge; border-radius: 5px; text-align: center;
}
QProgressBar::chunk { background: $selection; }
""").substitute(font=FONT, **COLORS)


class ThemedCheckBox(QCheckBox):
    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if not self.isChecked():
            return

        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        x, y = indicator.center().x(), indicator.center().y()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(COLORS["paper"]), 1.6, cap=Qt.PenCapStyle.RoundCap))
        painter.drawLine(x - 3, y, x, y + 3)
        painter.drawLine(x, y + 3, x + 5, y - 3)
        painter.end()


def document_palette(palette: QPalette) -> QPalette:
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(COLORS["paper"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(COLORS["muted"]))
    return palette
