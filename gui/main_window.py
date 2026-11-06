import os
from dataclasses import dataclass
from typing import List

from PyQt6.QtCore import (
    Qt,
    QThread,
    pyqtSignal,
    QObject,
    QSettings,
    pyqtProperty,
    QPropertyAnimation,
    QRect,
    QItemSelectionModel,
)
from PyQt6.QtGui import QCursor, QDrag, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QDialog,
    QDialogButtonBox,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QToolButton,
    QTableWidget,
    QTableWidgetItem,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from core.pdf_merger import PdfMergerService
from core.page_ranges import parse_page_order, parse_split_groups
from utils.file_utils import (
    format_bytes,
    format_modified,
    get_file_modified_timestamp,
    get_file_size_bytes,
    get_pdf_page_count,
    is_pdf_file,
    normalize_path,
    unique_pdf_paths,
)
from utils.resource_utils import resource_path


@dataclass
class PdfItem:
    path: str
    pages: int
    size_bytes: int
    modified_ts: float
    page_order: str = ""


class SortableItem(QTableWidgetItem):
    def __lt__(self, other: "QTableWidgetItem") -> bool:  # type: ignore[override]
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        if left is not None and right is not None:
            return left < right
        return super().__lt__(other)


class FileListWidget(QTableWidget):
    external_files_dropped = pyqtSignal(list)
    rows_reordered = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("DropArea")
        self.setColumnCount(7)
        self.setHorizontalHeaderLabels(
            ["#", "Document", "Size", "Pages", "Page order", "Output pages", "Modified"]
        )
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDropIndicatorShown(False)
        self.setDragDropOverwriteMode(False)
        self.setAlternatingRowColors(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(True)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(0, self.horizontalHeader().ResizeMode.Fixed)
        self.horizontalHeader().setSectionResizeMode(1, self.horizontalHeader().ResizeMode.Interactive)
        self.horizontalHeader().setSectionResizeMode(2, self.horizontalHeader().ResizeMode.Interactive)
        self.horizontalHeader().setSectionResizeMode(3, self.horizontalHeader().ResizeMode.Interactive)
        self.horizontalHeader().setSectionResizeMode(4, self.horizontalHeader().ResizeMode.Interactive)
        self.horizontalHeader().setSectionResizeMode(5, self.horizontalHeader().ResizeMode.Interactive)
        self.horizontalHeader().setSectionResizeMode(6, self.horizontalHeader().ResizeMode.Interactive)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.setSortingEnabled(True)
        self.horizontalHeader().setSortIndicatorShown(True)
        self.horizontalHeader().sectionClicked.connect(self._handle_header_sort)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.verticalHeader().setDefaultSectionSize(42)
        self.setAccessibleName("PDF files in output order")
        self.setColumnWidth(0, 36)
        self._last_sort_section: int | None = None
        self._sort_orders: dict[int, Qt.SortOrder] = {}

        self._placeholder = QLabel("Drop your PDFs here\n\nOr choose Add PDFs above to get started", self.viewport())
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setObjectName("DropLabel")
        self._placeholder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._drop_row: int | None = None
        self._drop_pos_y: int | None = None
        self._indicator_opacity = 0.0
        self._indicator_anim = QPropertyAnimation(self, b"indicatorOpacity", self)
        self._indicator_anim.setDuration(140)
        self._drag_rows: list[int] = []
        self._hover_row: int | None = None
        self._update_placeholder()

    def resizeEvent(self, event):  # type: ignore[override]
        super().resizeEvent(event)
        self._center_placeholder()

    def _center_placeholder(self) -> None:
        if not self._placeholder:
            return
        size = self.viewport().size()
        box_width = min(520, max(220, size.width() - 48))
        box_height = min(140, max(40, size.height() - 16))
        self._placeholder.setText(
            "Drop PDFs here or choose Add PDFs" if box_height < 110 else
            "Drop your PDFs here\n\nOr choose Add PDFs above to get started"
        )
        x = max(0, (size.width() - box_width) // 2)
        y = max(0, (size.height() - box_height) // 2)
        self._placeholder.setGeometry(x, y, box_width, box_height)

    def _update_placeholder(self) -> None:
        self._placeholder.setVisible(self.rowCount() == 0)
        self._center_placeholder()

    def dropEvent(self, event):  # type: ignore[override]
        # Allow reordering inside the list
        if event.source() is self:
            event.setDropAction(Qt.DropAction.CopyAction)
            pos = self._to_viewport_pos(event.position().toPoint())
            self._move_rows_to_target(self._drag_rows, self._drop_target_row(pos))
            self._drag_rows = []
            event.acceptProposedAction()
            self._clear_drop_row()
            return

        if event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            paths = [url.toLocalFile() for url in event.mimeData().urls()]
            self.external_files_dropped.emit(paths)
            event.acceptProposedAction()
        self._clear_drop_row()

    def dragEnterEvent(self, event):  # type: ignore[override]
        if event.source() is self:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):  # type: ignore[override]
        if event.source() is self:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.acceptProposedAction()
            pos = self._to_viewport_pos(event.position().toPoint())
            self._update_drop_row(pos)
        elif event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.acceptProposedAction()
            pos = self._to_viewport_pos(event.position().toPoint())
            self._update_drop_row(pos)
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):  # type: ignore[override]
        self._clear_drop_row()
        super().dragLeaveEvent(event)

    def leaveEvent(self, event):  # type: ignore[override]
        self._hover_row = None
        self.viewport().update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):  # type: ignore[override]
        index = self.indexAt(event.position().toPoint())
        row = index.row() if index.isValid() else None
        if self._hover_row != row:
            self._hover_row = row
            self.viewport().update()
        super().mouseMoveEvent(event)

    def startDrag(self, supportedActions) -> None:  # type: ignore[override]
        self._drag_rows = sorted({idx.row() for idx in self.selectionModel().selectedRows()})
        if self.isSortingEnabled():
            self.setSortingEnabled(False)
        indexes = self.selectionModel().selectedIndexes()
        if not indexes:
            return

        drag = QDrag(self)
        mime_data = self.model().mimeData(indexes)
        drag.setMimeData(mime_data)

        region = self.visualRegionForSelection(self.selectionModel().selection())
        rect = region.boundingRect()
        if not rect.isNull():
            pixmap = self.viewport().grab(rect)
            if not pixmap.isNull():
                translucent = QPixmap(pixmap.size())
                translucent.fill(Qt.GlobalColor.transparent)
                painter = QPainter(translucent)
                painter.setOpacity(0.5)
                painter.drawPixmap(0, 0, pixmap)
                painter.end()
                drag.setPixmap(translucent)
                cursor_pos = self.viewport().mapFromGlobal(QCursor.pos())
                drag.setHotSpot(cursor_pos - rect.topLeft())

        drag.exec(supportedActions)
        self._clear_drop_row()

    def paintEvent(self, event):  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        if self._hover_row is not None:
            if not self.selectionModel().isRowSelected(
                self._hover_row, self.model().index(self._hover_row, 0)
            ):
                hover_index = self.model().index(self._hover_row, 0)
                hover_rect = self.visualRect(hover_index)
                hover_rect.setLeft(0)
                hover_rect.setRight(self.viewport().width())
                hover_color = self.palette().color(QPalette.ColorRole.Highlight)
                hover_color.setAlpha(40)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(hover_color)
                painter.drawRect(hover_rect)

        if self._drop_row is None or self._drop_pos_y is None or self._indicator_opacity <= 0:
            return
        color = self.palette().color(QPalette.ColorRole.Highlight)
        color.setAlphaF(min(0.6, max(0.0, self._indicator_opacity)))
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        left = 4
        right = self.viewport().width() - 4
        y = self._drop_pos_y
        height = 8
        rect = QRect(left, y - height // 2, right - left, height)
        painter.drawRoundedRect(rect, 4, 4)

    def add_row(self) -> int:
        row = self.rowCount()
        self.insertRow(row)
        self._update_placeholder()
        return row

    def clear_rows(self) -> None:
        self.setRowCount(0)
        self._update_placeholder()

    def remove_row(self, row: int) -> None:
        self.removeRow(row)
        self._update_placeholder()

    def _set_drop_row(self, row: int | None) -> None:
        if self._drop_row == row:
            return
        self._drop_row = row
        self._fade_indicator(1.0)
        self.viewport().update()

    def _clear_drop_row(self) -> None:
        if self._drop_row is None:
            return
        self._fade_indicator(0.0)

    def _update_drop_row(self, pos) -> None:
        if self.rowCount() == 0:
            self._drop_pos_y = self.viewport().rect().center().y()
            self._set_drop_row(0)
            return
        row = self._drop_target_row(pos)
        self._drop_pos_y = self._drop_indicator_y(row)
        self._set_drop_row(row)

    def _drop_target_row(self, pos) -> int:
        index = self.indexAt(pos)
        if index.isValid():
            rect = self.visualRect(index)
            return index.row() + (1 if pos.y() >= rect.center().y() else 0)
        return self.rowCount()

    def _drop_indicator_y(self, target_row: int) -> int:
        if self.rowCount() == 0:
            return self.viewport().rect().center().y()
        if target_row <= 0:
            first_rect = self.visualRect(self.model().index(0, 0))
            return first_rect.top()
        if target_row >= self.rowCount():
            last_rect = self.visualRect(self.model().index(self.rowCount() - 1, 0))
            return last_rect.bottom()
        rect = self.visualRect(self.model().index(target_row, 0))
        return rect.top()

    def _move_rows_to_target(self, rows: list[int], target_row: int, *, preview: bool = False) -> None:
        if not rows:
            return

        rows = sorted(set(rows))

        row_data: list[list[QTableWidgetItem | None]] = []
        for row in rows:
            items: list[QTableWidgetItem | None] = []
            for col in range(self.columnCount()):
                item = self.item(row, col)
                items.append(SortableItem(item) if isinstance(item, SortableItem)
                             else QTableWidgetItem(item) if item else None)
            row_data.append(items)

        self.setUpdatesEnabled(False)
        self.setSortingEnabled(False)
        try:
            for row in reversed(rows):
                self.removeRow(row)

            offset = sum(1 for row in rows if row < target_row)
            target_row -= offset
            target_row = max(0, min(target_row, self.rowCount()))

            insert_at = target_row
            for items in row_data:
                self.insertRow(insert_at)
                for col, item in enumerate(items):
                    self.setItem(insert_at, col, item or QTableWidgetItem(""))
                insert_at += 1

            if not preview:
                self.clearSelection()
                for row in range(target_row, target_row + len(row_data)):
                    self.selectionModel().select(
                        self.model().index(row, 0),
                        QItemSelectionModel.SelectionFlag.Select |
                        QItemSelectionModel.SelectionFlag.Rows,
                    )
                self._update_placeholder()
        finally:
            self.setUpdatesEnabled(True)
        self.rows_reordered.emit()

    # Preview reordering is intentionally disabled to prevent jitter.

    def _to_viewport_pos(self, pos):
        # Item-view drag events already use viewport coordinates.
        return pos

    def _handle_header_sort(self, section: int) -> None:
        if not self.isSortingEnabled():
            self.setSortingEnabled(True)
        if self._last_sort_section == section:
            current_order = self._sort_orders.get(section, Qt.SortOrder.AscendingOrder)
            new_order = (
                Qt.SortOrder.DescendingOrder
                if current_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            new_order = Qt.SortOrder.AscendingOrder
        self._last_sort_section = section
        self._sort_orders[section] = new_order
        self.horizontalHeader().setSortIndicator(section, new_order)
        self.sortItems(section, new_order)

    def _fade_indicator(self, target: float) -> None:
        self._indicator_anim.stop()
        self._indicator_anim.setStartValue(self._indicator_opacity)
        self._indicator_anim.setEndValue(target)
        self._indicator_anim.start()

    def _get_indicator_opacity(self) -> float:
        return self._indicator_opacity

    def _set_indicator_opacity(self, value: float) -> None:
        self._indicator_opacity = value
        if value <= 0.0 and self._indicator_anim.endValue() == 0.0:
            self._drop_row = None
        self.viewport().update()

    indicatorOpacity = pyqtProperty(float, _get_indicator_opacity, _set_indicator_opacity)


class PageSelectionDialog(QDialog):
    def __init__(self, parent, title, description, text, page_count, split=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(540)
        self.page_count = page_count
        self.split = split
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        help_text = QLabel(description)
        help_text.setWordWrap(True)
        help_text.setObjectName("Muted")
        layout.addWidget(help_text)
        self.edit = QLineEdit(text)
        self.edit.setAccessibleName("Split page groups" if split else "Page order")
        self.edit.setPlaceholderText("Example: 1-3; 4-6" if split else "Example: 3, 1-2, 5-4")
        layout.addWidget(self.edit)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(48)
        self.preview.setAccessibleName("Output preview or validation error")
        layout.addWidget(self.preview)
        reset = QToolButton()
        reset.setText("One file per page" if split else "Restore all pages")
        reset.clicked.connect(self.edit.clear)
        layout.addWidget(reset, alignment=Qt.AlignmentFlag.AlignLeft)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Split and save" if split else "Apply page order")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.edit.textChanged.connect(self._validate)
        self._validate()
        self.edit.setFocus()

    def _validate(self):
        try:
            if self.split:
                groups = parse_split_groups(self.edit.text(), self.page_count)
                summary = f"Ready to save {len(groups)} PDFs, containing {sum(map(len, groups))} pages in total."
            else:
                pages = parse_page_order(self.edit.text(), self.page_count)
                sequence = ", ".join(str(p + 1) for p in pages[:18])
                if len(pages) > 18:
                    sequence += ", ..."
                summary = f"{len(pages)} output pages\nOrder: {sequence}"
            self.preview.setText(summary)
            self.preview.setStyleSheet("color: #a8d9bb;")
            valid = True
        except ValueError as exc:
            self.preview.setText(f"Check your pages: {exc}")
            self.preview.setStyleSheet("color: #ffb4ae;")
            valid = False
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    @staticmethod
    def getText(parent, title, description, *, text="", page_count, split=False):
        dialog = PageSelectionDialog(parent, title, description, text, page_count, split)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return dialog.edit.text(), accepted


class MergeWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, paths: List[str], output_path: str, overwrite: bool = False,
                 page_orders=None, split_outputs=None, split_groups=None) -> None:
        super().__init__()
        self._paths = paths
        self._output_path = output_path
        self._overwrite = overwrite
        self._merger = PdfMergerService()
        self._page_orders = page_orders
        self._split_outputs = split_outputs
        self._split_groups = split_groups

    def run(self) -> None:
        try:
            if self._split_outputs is not None:
                self._merger.split(self._paths[0], self._split_outputs, self._split_groups,
                                   self._emit_progress, overwrite=self._overwrite)
                self.finished.emit(True, f"Saved {len(self._split_outputs)} split PDFs.")
            else:
                self._merger.merge(self._paths, self._output_path, self._emit_progress,
                                   overwrite=self._overwrite, page_orders=self._page_orders)
                self.finished.emit(True, "PDF saved successfully.")
        except Exception as exc:
            self.finished.emit(False, f"PDF operation failed: {exc}")

    def _emit_progress(self, current: int, total: int, path: str) -> None:
        self.progress.emit(current, total, os.path.basename(path))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDF Merger")
        icon_ico = resource_path(os.path.join("gui", "assets", "app_icon.ico"))
        if os.path.exists(icon_ico):
            self.setWindowIcon(QIcon(icon_ico))
        self.resize(1040, 780)
        self.setMinimumSize(800, 660)

        self._settings = QSettings("PDFMergePro", "PDF Merge Pro")
        self._dark_mode = True

        self._items: dict[str, PdfItem] = {}
        self._thread: QThread | None = None
        self._worker: MergeWorker | None = None
        self._progress_dialog: QProgressDialog | None = None

        self._build_ui()
        self._apply_theme()

    def _build_ui(self) -> None:
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(24, 22, 24, 12)
        main_layout.setSpacing(14)

        title = QLabel("PDF Merger")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Combine documents, reorder pages, or split a PDF into separate files.")
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        main_layout.addWidget(title)
        main_layout.addWidget(subtitle)

        toolbar_layout = QHBoxLayout()
        section = QLabel("1   Organize your files")
        section.setObjectName("SectionTitle")
        toolbar_layout.addWidget(section)
        toolbar_layout.addStretch()
        self.add_button = QToolButton()
        self.add_button.setText("Add PDFs")
        self.add_button.setObjectName("AddButton")
        self.add_button.setShortcut("Ctrl+O")
        self.add_button.setToolTip("Choose PDF files (Ctrl+O)")
        self.clear_button = QToolButton()
        self.clear_button.setText("Clear all")
        self.clear_button.setToolTip("Remove every file from this list; original files are kept")
        toolbar_layout.addWidget(self.add_button)
        toolbar_layout.addWidget(self.clear_button)
        main_layout.addLayout(toolbar_layout)

        self.list_widget = FileListWidget()
        self.list_widget.external_files_dropped.connect(self._handle_files_dropped)
        self.list_widget.rows_reordered.connect(self._reindex_rows)
        self.list_widget.rows_reordered.connect(self._update_action_state)
        self.list_widget.selectionModel().selectionChanged.connect(self._update_action_state)
        header = self.list_widget.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column, width in [(0, 40), (2, 80), (3, 65), (4, 145), (5, 105)]:
            self.list_widget.setColumnWidth(column, width)
        self.list_widget.setColumnHidden(6, True)
        self.list_widget.setMinimumHeight(120)
        self.list_widget.cellDoubleClicked.connect(lambda row, col: self._edit_page_order())
        main_layout.addWidget(self.list_widget, 1)

        actions = QHBoxLayout()
        self.remove_button = QToolButton()
        self.remove_button.setText("Remove")
        self.remove_button.setToolTip("Remove selected files from the list")
        self.move_up_button = QToolButton()
        self.move_up_button.setText("Move up")
        self.move_down_button = QToolButton()
        self.move_down_button.setText("Move down")
        self.pages_button = QToolButton()
        self.pages_button.setText("Rearrange pages")
        self.pages_button.setToolTip("Select one PDF to change page order or extract pages. Double-click also works.")
        self.split_button = QToolButton()
        self.split_button.setText("Split PDF")
        self.split_button.setToolTip("Select one PDF to save page groups as separate files")
        for button in (self.remove_button, self.move_up_button, self.move_down_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self.pages_button)
        actions.addWidget(self.split_button)
        main_layout.addLayout(actions)

        self.selection_hint = QLabel("Add PDFs to begin. Files are saved in the order shown above.")
        self.selection_hint.setObjectName("Muted")
        self.selection_hint.setWordWrap(True)
        main_layout.addWidget(self.selection_hint)

        self.add_button.clicked.connect(self._add_files_dialog)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear_list)
        self.move_up_button.clicked.connect(lambda: self._move_selection(-1))
        self.move_down_button.clicked.connect(lambda: self._move_selection(1))
        self.pages_button.clicked.connect(self._edit_page_order)
        self.split_button.clicked.connect(self._split_pdf)

        output_card = QWidget()
        output_card.setObjectName("OutputCard")
        output = QGridLayout(output_card)
        output.setContentsMargins(18, 16, 18, 16)
        output.setHorizontalSpacing(12)
        output.setVerticalSpacing(10)
        output_title = QLabel("2   Choose where to save")
        output_title.setObjectName("SectionTitle")
        output.addWidget(output_title, 0, 0, 1, 3)
        dest_label = QLabel("Destination folder")
        name_label = QLabel("File name (.pdf)")
        self.dest_input = QLineEdit()
        self.dest_input.setMinimumHeight(40)
        self.dest_input.setAccessibleName("Destination folder")
        self.dest_input.setPlaceholderText("Choose a folder for your PDFs")
        last_dir = self._settings.value("output/last_dir", "", type=str)
        if last_dir and os.path.isdir(last_dir):
            self.dest_input.setText(last_dir)
        self.dest_browse_button = QToolButton()
        self.dest_browse_button.setText("Browse...")
        self.dest_browse_button.clicked.connect(self._browse_destination)
        self.filename_input = QLineEdit("Merge")
        self.filename_input.setMinimumHeight(40)
        self.filename_input.setAccessibleName("Output PDF file name")
        self.filename_input.setPlaceholderText("Merge")
        self.filename_input.setMinimumWidth(130)
        self.filename_input.setMaximumWidth(240)
        dest_label.setBuddy(self.dest_input)
        name_label.setBuddy(self.filename_input)
        output.addWidget(dest_label, 1, 0)
        output.addWidget(name_label, 1, 2)
        output.addWidget(self.dest_input, 2, 0)
        output.addWidget(self.dest_browse_button, 2, 1)
        output.addWidget(self.filename_input, 2, 2)
        output.setColumnStretch(0, 1)
        self.overwrite_checkbox = QCheckBox("Replace existing output files")
        self.overwrite_checkbox.setToolTip("Original input PDFs are always protected")
        output.addWidget(self.overwrite_checkbox, 3, 0, 1, 3)
        main_layout.addWidget(output_card)

        export_row = QHBoxLayout()
        self.total_pages_label = QLabel("Total pages: 0")
        self.total_pages_label.setObjectName("TotalPagesLabel")
        self.file_count_label = QLabel("0 files")
        self.file_count_label.setObjectName("Muted")
        export_row.addWidget(self.total_pages_label)
        export_row.addWidget(self.file_count_label)
        export_row.addStretch()
        self.merge_button = QPushButton("Merge / Save PDF")
        self.merge_button.setObjectName("MergeButton")
        self.merge_button.setMinimumWidth(210)
        self.merge_button.clicked.connect(self._merge_pdfs)
        export_row.addWidget(self.merge_button)
        main_layout.addLayout(export_row)

        self.created_by_label = QLabel("Created by Shafiq  /  Files stay on your computer")
        self.created_by_label.setObjectName("CreatedByLabel")
        main_layout.addWidget(self.created_by_label)
        self.setCentralWidget(central)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        self.menuBar().setVisible(False)
        self._update_action_state()

    def _add_files_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select PDF files",
            "",
            "PDF Files (*.pdf)",
        )
        if paths:
            self._handle_files_dropped(paths)

    def _browse_destination(self) -> None:
        last_dir = self._settings.value("output/last_dir", "", type=str)
        folder = QFileDialog.getExistingDirectory(self, "Select destination folder", last_dir or "")
        if folder:
            self.dest_input.setText(folder)
            self._settings.setValue("output/last_dir", folder)

    def _handle_files_dropped(self, paths: List[str]) -> None:
        # Normalize and dedupe incoming files
        unique_paths = unique_pdf_paths(paths)
        if not unique_paths:
            self._show_status("No valid PDF files found.")
            return

        added_count = 0
        for path in unique_paths:
            norm = normalize_path(path)
            if norm in self._items:
                continue
            if not is_pdf_file(path):
                continue

            ok, pages, error = get_pdf_page_count(path)
            if not ok:
                self._show_message("PDF Error", f"Skipped {os.path.basename(path)}: {error}", QMessageBox.Icon.Warning)
                continue

            try:
                size_bytes = get_file_size_bytes(path)
                modified_ts = get_file_modified_timestamp(path)
            except OSError as exc:
                self._show_message("PDF Error", f"Skipped {os.path.basename(path)}: {exc}",
                                   QMessageBox.Icon.Warning)
                continue
            item = PdfItem(path=path, pages=pages, size_bytes=size_bytes, modified_ts=modified_ts)
            self._items[norm] = item
            self._add_list_item(item)
            added_count += 1

        if added_count:
            self._show_status(f"Added {added_count} PDF file(s).")
        self._reindex_rows()
        self._update_action_state()

    def _add_list_item(self, item: PdfItem) -> None:
        was_sorting = self.list_widget.isSortingEnabled()
        self.list_widget.setSortingEnabled(False)
        row = self.list_widget.add_row()

        index_item = SortableItem()
        index_item.setData(Qt.ItemDataRole.DisplayRole, str(row + 1))
        index_item.setData(Qt.ItemDataRole.UserRole, row + 1)

        name_item = QTableWidgetItem(os.path.basename(item.path))
        name_item.setData(Qt.ItemDataRole.UserRole, item.path)
        name_item.setToolTip(f"{item.path}\nModified: {format_modified(item.modified_ts)}")

        size_item = SortableItem()
        size_item.setData(Qt.ItemDataRole.DisplayRole, format_bytes(item.size_bytes))
        size_item.setData(Qt.ItemDataRole.UserRole, item.size_bytes)

        pages_item = SortableItem()
        pages_item.setData(Qt.ItemDataRole.DisplayRole, str(item.pages))
        pages_item.setData(Qt.ItemDataRole.UserRole, item.pages)

        ranges_item = QTableWidgetItem(item.page_order or "All")
        selected_pages_item = SortableItem(str(item.pages))
        selected_pages_item.setData(Qt.ItemDataRole.UserRole, item.pages)

        modified_item = SortableItem()
        modified_item.setData(Qt.ItemDataRole.DisplayRole, format_modified(item.modified_ts))
        modified_item.setData(Qt.ItemDataRole.UserRole, item.modified_ts)

        self.list_widget.setItem(row, 0, index_item)
        self.list_widget.setItem(row, 1, name_item)
        self.list_widget.setItem(row, 2, size_item)
        self.list_widget.setItem(row, 3, pages_item)
        self.list_widget.setItem(row, 4, ranges_item)
        self.list_widget.setItem(row, 5, selected_pages_item)
        self.list_widget.setItem(row, 6, modified_item)
        self.list_widget.setSortingEnabled(was_sorting)

        self._update_total_pages()

    def _remove_selected(self) -> None:
        selection = self.list_widget.selectionModel().selectedRows()
        if not selection:
            self._show_status("No items selected.")
            return
        rows = sorted([index.row() for index in selection], reverse=True)
        for row in rows:
            name_item = self.list_widget.item(row, 1)
            path = name_item.data(Qt.ItemDataRole.UserRole) if name_item else None
            if path:
                self._items.pop(normalize_path(path), None)
            self.list_widget.remove_row(row)
        self._reindex_rows()
        self._update_total_pages()
        self._update_action_state()
        self._show_status("Removed selected items.")

    def _clear_list(self) -> None:
        self.list_widget.clear_rows()
        self._items.clear()
        self._update_total_pages()
        self._update_action_state()
        self._show_status("List cleared.")

    def _selected_pdf(self):
        selection = self.list_widget.selectionModel().selectedRows()
        if len(selection) != 1 or self._thread is not None:
            return None
        row = selection[0].row()
        path = self.list_widget.item(row, 1).data(Qt.ItemDataRole.UserRole)
        return row, self._items[normalize_path(path)]

    def _edit_page_order(self) -> None:
        selected = self._selected_pdf()
        if selected is None:
            return
        row, item = selected
        text = item.page_order
        while True:
            text, accepted = PageSelectionDialog.getText(
                self, "Rearrange / extract pages",
                f"{os.path.basename(item.path)} - {item.pages} pages\n"
                "Enter pages in output order, e.g. 3, 1-2, 5-4.\n"
                "Blank restores all pages. Repeated pages are allowed.\n"
                "Then use Save PDF or Merge PDFs to export.", text=text, page_count=item.pages)
            if not accepted:
                return
            try:
                pages = parse_page_order(text, item.pages)
            except ValueError as exc:
                self._show_message("Invalid pages", str(exc), QMessageBox.Icon.Warning)
                continue
            item.page_order = text.strip()
            was_sorting = self.list_widget.isSortingEnabled()
            self.list_widget.setSortingEnabled(False)
            self.list_widget.item(row, 4).setText(item.page_order or "All")
            count_item = self.list_widget.item(row, 5)
            count_item.setText(str(len(pages)))
            count_item.setData(Qt.ItemDataRole.UserRole, len(pages))
            self.list_widget.setSortingEnabled(was_sorting)
            self._update_total_pages()
            return

    def _split_pdf(self) -> None:
        selected = self._selected_pdf()
        if selected is None:
            return
        _, item = selected
        destination = self.dest_input.text().strip()
        if not os.path.isdir(destination):
            self._show_status("Select an existing destination folder before splitting.")
            return
        text = ""
        while True:
            text, accepted = PageSelectionDialog.getText(
                self, "Split PDF",
                f"{os.path.basename(item.path)} - {item.pages} original pages\n"
                "Separate output groups with semicolons: 1-3; 4-6; 7\n"
                "Leave blank for one PDF per page. Uses original page numbers.\n"
                "Saves as <source>_part_001.pdf, <source>_part_002.pdf, etc.\n"
                "The replace-files setting applies to all split outputs.", text=text,
                page_count=item.pages, split=True)
            if not accepted:
                return
            try:
                groups = parse_split_groups(text, item.pages)
            except ValueError as exc:
                self._show_message("Invalid split", str(exc), QMessageBox.Icon.Warning)
                continue
            break
        stem = os.path.splitext(os.path.basename(item.path))[0]
        outputs = [os.path.join(destination, f"{stem}_part_{i:03d}.pdf")
                   for i in range(1, len(groups) + 1)]
        self._start_worker(MergeWorker([item.path], "", self.overwrite_checkbox.isChecked(),
                                       split_outputs=outputs, split_groups=groups), len(groups))

    def _merge_pdfs(self) -> None:
        if self._thread is not None:
            return
        paths = self._ordered_paths()
        if not paths:
            self._show_status("Add PDFs before merging.")
            return

        destination = self.dest_input.text().strip()
        if not destination:
            self._show_status("Select a destination folder.")
            return

        if not os.path.isdir(destination):
            self._show_status("Select an existing destination folder.")
            return

        filename = self.filename_input.text().strip() or "Merge"
        if filename in (".", "..") or any(c in filename for c in '<>:"/\\|?*'):
            self._show_status("Enter a file name without folders or invalid characters.")
            return
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"
        output_path = os.path.join(destination, filename)

        if os.path.exists(output_path) and not self.overwrite_checkbox.isChecked():
            self._show_message(
                "File Exists",
                "A file with this name already exists. Enable overwrite to replace it.",
                QMessageBox.Icon.Warning,
            )
            return

        page_orders = [parse_page_order(self._items[normalize_path(path)].page_order,
                                       self._items[normalize_path(path)].pages) for path in paths]
        self._start_worker(MergeWorker(paths, output_path, self.overwrite_checkbox.isChecked(),
                                       page_orders=page_orders), len(paths))

    def _start_worker(self, worker: MergeWorker, total: int) -> None:
        self._settings.setValue("output/last_dir", self.dest_input.text().strip())
        self._progress_dialog = QProgressDialog("Processing PDFs...", "Cancel", 0, total, self)
        self._progress_dialog.setWindowTitle("Processing PDFs")
        self._progress_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._progress_dialog.setCancelButton(None)
        self._progress_dialog.setAutoClose(False)
        self._progress_dialog.setAutoReset(False)
        self._progress_dialog.setValue(0)
        self._progress_dialog.show()

        self.centralWidget().setEnabled(False)
        self._thread = QThread(self)
        self._worker = worker
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._update_progress)
        self._worker.finished.connect(self._merge_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    def _update_progress(self, current: int, total: int, filename: str) -> None:
        if self._progress_dialog:
            self._progress_dialog.setMaximum(total)
            self._progress_dialog.setValue(current)
            self._progress_dialog.setLabelText(f"Processing {filename} ({current}/{total})...")

    def _merge_finished(self, ok: bool, message: str) -> None:
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None
        if ok:
            self._show_message("Success", message, QMessageBox.Icon.Information)
            self._show_status(message)
        else:
            self._show_message("Error", message, QMessageBox.Icon.Critical)
            self._show_status(message)

    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.centralWidget().setEnabled(True)

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            self._show_status("Wait for the PDF operation to finish before closing.")
            event.ignore()
            return
        super().closeEvent(event)

    def _ordered_paths(self) -> List[str]:
        paths = []
        for row in range(self.list_widget.rowCount()):
            item = self.list_widget.item(row, 1)
            path = item.data(Qt.ItemDataRole.UserRole) if item else None
            if path:
                paths.append(path)
        return paths

    def _set_tool_button_state(self, button: QToolButton, enabled: bool) -> None:
        button.setEnabled(enabled)
        button.setObjectName("ToolButton" if enabled else "ToolButtonDisabled")
        button.style().unpolish(button)
        button.style().polish(button)

    def _update_action_state(self) -> None:
        selection = self.list_widget.selectionModel().selectedRows()
        has_selection = bool(selection)
        if has_selection:
            rows = [index.row() for index in selection]
            min_row = min(rows)
            max_row = max(rows)
        else:
            min_row = 0
            max_row = -1

        can_move_up = has_selection and min_row > 0
        can_move_down = has_selection and max_row < self.list_widget.rowCount() - 1

        self._set_tool_button_state(self.pages_button, len(selection) == 1)
        self._set_tool_button_state(self.split_button, len(selection) == 1)
        self._set_tool_button_state(self.remove_button, has_selection)
        self._set_tool_button_state(self.move_up_button, can_move_up)
        self._set_tool_button_state(self.move_down_button, can_move_down)
        count = self.list_widget.rowCount()
        self.clear_button.setEnabled(count > 0)
        self.merge_button.setEnabled(count > 0)
        self.merge_button.setText("Save PDF" if count == 1 else "Merge PDFs" if count else "Merge / Save PDF")
        self.file_count_label.setText(f"{count} file{'s' if count != 1 else ''}")
        if len(selection) == 1:
            self.selection_hint.setText("1 file selected. Rearrange its pages, split it, or move it in the list.")
        elif selection:
            self.selection_hint.setText(f"{len(selection)} files selected. Move or remove them together.")
        elif count:
            self.selection_hint.setText("Drag rows to change file order. Select one PDF to rearrange or split its pages.")
        else:
            self.selection_hint.setText("Add PDFs to begin. Files are saved in the order shown above.")

    def _move_selection(self, direction: int) -> None:
        selection = self.list_widget.selectionModel().selectedRows()
        if not selection:
            return
        rows = sorted({index.row() for index in selection})
        if direction < 0:
            min_row = rows[0]
            if min_row <= 0:
                return
            target_row = min_row - 1
        else:
            max_row = rows[-1]
            if max_row >= self.list_widget.rowCount() - 1:
                return
            target_row = max_row + 2
        self.list_widget._move_rows_to_target(rows, target_row)
        self._reindex_rows()
        self._update_action_state()

    def _reindex_rows(self) -> None:
        was_sorting = self.list_widget.isSortingEnabled()
        self.list_widget.setSortingEnabled(False)
        for row in range(self.list_widget.rowCount()):
            index_item = self.list_widget.item(row, 0)
            if index_item:
                index_item.setData(Qt.ItemDataRole.DisplayRole, str(row + 1))
                index_item.setData(Qt.ItemDataRole.UserRole, row + 1)
        if was_sorting and self.list_widget.horizontalHeader().sortIndicatorSection() == 0:
            # The new sequence numbers describe the current order; do not reverse it.
            self.list_widget.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.list_widget.setSortingEnabled(was_sorting)

    def _update_total_pages(self) -> None:
        total = sum(len(parse_page_order(item.page_order, item.pages))
                    for item in self._items.values() if item.pages)
        self.total_pages_label.setText(f"Total pages: {total}")

    def _apply_theme(self) -> None:
        self.setStyleSheet("""
            QWidget { font-family: 'Segoe UI'; font-size: 13px; color: #e7edf6; }
            QMainWindow, QDialog, QMessageBox { background: #151922; }
            QLabel { background: transparent; }
            QLabel#PageTitle { font-size: 28px; font-weight: 700; }
            QLabel#SectionTitle { font-size: 14px; font-weight: 600; }
            QLabel#Muted, QLabel#CreatedByLabel { color: #a7b3c5; }
            QLabel#CreatedByLabel { font-size: 11px; }
            QWidget#OutputCard { background: #1c2330; border: 1px solid #333e50; border-radius: 10px; }
            QLabel#DropLabel { color: #a7b3c5; background: #1c2330; border: 2px dashed #46546b;
                              border-radius: 12px; font-size: 15px; }
            QTableWidget { background: #191f2a; border: 1px solid #333e50; border-radius: 8px;
                           selection-background-color: #284775; selection-color: #ffffff; }
            QTableWidget::item { padding: 6px; border-bottom: 1px solid #252f40; }
            QTableWidget::item:selected { background: #284775; color: #ffffff; }
            QTableWidget::item:focus { border: 1px solid #8ab4ff; }
            QHeaderView::section { background: #222b3a; color: #b9c6d9; border: none;
                                   padding: 11px 6px; font-weight: 600; }
            QToolButton, QPushButton { background: #252f40; border: 1px solid #455269;
                                       border-radius: 7px; padding: 8px 13px; min-height: 20px; }
            QToolButton:hover, QPushButton:hover { background: #34425a; border-color: #7086a7; }
            QToolButton:pressed, QPushButton:pressed { background: #19253b; }
            QToolButton:disabled, QPushButton:disabled { color: #8591a4; background: #1d2532; border-color: #303b4d; }
            QToolButton:focus, QPushButton:focus, QLineEdit:focus { border: 2px solid #98bfff; }
            QToolButton#AddButton { background: #284775; border-color: #5883c0; }
            QPushButton#MergeButton { background: #376ad9; border-color: #6b99fa; color: #ffffff;
                                      font-weight: 600; padding: 11px 22px; }
            QPushButton#MergeButton:hover { background: #4279ed; }
            QPushButton#MergeButton:disabled { background: #253249; border-color: #3a4a64; color: #9aaac3; }
            QLineEdit { background: #141b27; border: 1px solid #455269; border-radius: 6px;
                        padding: 9px 10px; selection-background-color: #376ad9; }
            QCheckBox { spacing: 9px; padding-top: 4px; }
            QCheckBox:focus { outline: 1px solid #98bfff; }
            QLabel#TotalPagesLabel { font-weight: 600; padding-right: 8px; }
            QStatusBar { background: #151922; color: #a7b3c5; }
            QToolTip { background: #24324a; color: #ffffff; border: 1px solid #7086a7; padding: 6px; }
            QProgressBar { background: #141b27; border: 1px solid #455269; border-radius: 5px; text-align: center; }
            QProgressBar::chunk { background: #376ad9; }
        """)

    def _show_status(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)

    def _show_message(self, title: str, message: str, icon: QMessageBox.Icon) -> None:
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(message)
        box.exec()
