import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt, QItemSelectionModel
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication
from pypdf import PdfReader, PdfWriter

from core.pdf_merger import PdfMergerService
from core.page_ranges import parse_page_order, parse_split_groups
from gui.main_window import MainWindow, SortableItem, PageSelectionDialog
from PyQt6.QtWidgets import QDialogButtonBox


def pdf(path, widths):
    with PdfWriter() as writer:
        for width in widths:
            writer.add_blank_page(width=width, height=100)
        writer.write(path)


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a = self.root / "a.pdf"
        self.b = self.root / "b.pdf"
        self.out = self.root / "out.pdf"
        pdf(self.a, [100, 200])
        pdf(self.b, [300])
        self.service = PdfMergerService()

    def test_order_and_progress(self):
        progress = []
        self.service.merge([self.b, self.a], self.out, lambda *args: progress.append(args))
        self.assertEqual([float(p.mediabox.width) for p in PdfReader(self.out).pages], [300, 100, 200])
        self.assertEqual([p[:2] for p in progress], [(1, 2), (2, 2)])

    def test_page_order_parser(self):
        self.assertEqual(parse_page_order("3, 1-2, 3-2", 3), [2, 0, 1, 2, 1])
        self.assertEqual(parse_page_order("", 3), [0, 1, 2])
        for text in ["0", "4", "1,", "a", "-1", "1-4", "1--2"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_page_order(text, 3)
        self.assertEqual(parse_split_groups("", 3), [[0], [1], [2]])
        self.assertEqual(parse_split_groups("2-1; 3", 3), [[1, 0], [2]])
        with self.assertRaises(ValueError):
            parse_split_groups("1;", 3)

    def test_rearrange_extract_and_repeat_pages(self):
        self.service.merge([self.a, self.b], self.out, page_orders=[[1, 0, 1], [0]])
        self.assertEqual([float(p.mediabox.width) for p in PdfReader(self.out).pages],
                         [200, 100, 200, 300])
        with self.assertRaises(ValueError):
            self.service.merge([self.a], self.root / "bad.pdf", page_orders=[[2]])
        self.assertFalse((self.root / "bad.pdf").exists())

    def test_split_outputs_and_conflict_preflight(self):
        outputs = [str(self.root / "part1.pdf"), str(self.root / "part2.pdf")]
        Path(outputs[1]).write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            self.service.split(self.a, outputs, [[1], [0]])
        self.assertFalse(Path(outputs[0]).exists())
        self.service.split(self.a, outputs, [[1], [0]], overwrite=True)
        self.assertEqual([float(PdfReader(p).pages[0].mediabox.width) for p in outputs], [200, 100])

    def test_split_invalid_plan_creates_no_files(self):
        outputs = [str(self.root / "part1.pdf"), str(self.root / "part2.pdf")]
        with self.assertRaises(ValueError):
            self.service.split(self.a, outputs, [[0], [9]])
        self.assertFalse(any(Path(p).exists() for p in outputs))
        with self.assertRaises(ValueError):
            self.service.split(self.a, [str(self.a)], [[0]], overwrite=True)

    def test_empty_input_rejected(self):
        with self.assertRaises(ValueError):
            self.service.merge([], self.out)
        self.assertFalse(self.out.exists())

    def test_input_cannot_be_overwritten(self):
        before = self.a.read_bytes()
        with self.assertRaises(ValueError):
            self.service.merge([self.a], self.a, overwrite=True)
        self.assertEqual(self.a.read_bytes(), before)

    def test_write_failure_preserves_destination_and_cleans_temp(self):
        self.out.write_bytes(b"original")
        def fail(writer, stream):
            stream.write(b"partial")
            raise OSError("disk full")
        with patch.object(PdfWriter, "write", fail):
            with self.assertRaises(OSError):
                self.service.merge([self.a], self.out, overwrite=True)
        self.assertEqual(self.out.read_bytes(), b"original")
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_existing_and_racing_outputs_are_preserved(self):
        self.out.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            self.service.merge([self.a], self.out)
        self.out.unlink()
        with self.assertRaises(FileExistsError):
            self.service.merge([self.a], self.out, lambda *args: self.out.write_bytes(b"raced"))
        self.assertEqual(self.out.read_bytes(), b"raced")
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_explicit_overwrite(self):
        self.out.write_bytes(b"original")
        self.service.merge([self.a], self.out, overwrite=True)
        self.assertEqual(len(PdfReader(self.out).pages), 2)

    def test_corrupt_input_does_not_publish(self):
        self.b.write_bytes(b"not a pdf")
        with self.assertRaises(Exception):
            self.service.merge([self.a, self.b], self.out)
        self.assertFalse(self.out.exists())


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = MainWindow()
        self.window._show_message = lambda *args: None
        self.addCleanup(self.window.close)
        self.paths = []
        for name, pages in [("c", 3), ("a", 1), ("b", 2), ("d", 4)]:
            path = str(Path(self.temp.name) / (name + ".pdf"))
            pdf(path, [100] * pages)
            self.paths.append(path)
        self.window._handle_files_dropped(self.paths)

    def select(self, rows):
        table = self.window.list_widget
        table.clearSelection()
        for row in rows:
            table.selectionModel().select(table.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def test_sorted_insert_keeps_rows_intact(self):
        table = self.window.list_widget
        table.sortItems(1, Qt.SortOrder.AscendingOrder)
        path = str(Path(self.temp.name) / "aa.pdf")
        pdf(path, [100] * 5)
        self.window._handle_files_dropped([path])
        for row in range(table.rowCount()):
            path = table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            self.assertEqual(int(table.item(row, 3).text()), len(PdfReader(path).pages))
            self.assertTrue(all(table.item(row, col) is not None for col in range(7)))

    def test_initial_order_matches_added_order(self):
        self.assertEqual(self.window._ordered_paths(), self.paths)

    def test_removal_after_descending_index_sort_preserves_order(self):
        table = self.window.list_widget
        table.sortItems(0, Qt.SortOrder.DescendingOrder)
        before = self.window._ordered_paths()
        self.select([1])
        self.window._remove_selected()
        self.assertEqual(self.window._ordered_paths(), [before[0], before[2], before[3]])

    def test_manual_move_survives_sorting_and_preserves_selection(self):
        table = self.window.list_widget
        table.sortItems(1, Qt.SortOrder.AscendingOrder)
        before = self.window._ordered_paths()
        self.select([1, 2])
        self.window._move_selection(-1)
        self.assertEqual(self.window._ordered_paths(), [before[1], before[2], before[0], before[3]])
        self.assertEqual(sorted(i.row() for i in table.selectionModel().selectedRows()), [0, 1])
        self.assertIsInstance(table.item(0, 3), SortableItem)
        self.assertEqual([table.item(r, 0).text() for r in range(4)], ["1", "2", "3", "4"])

    def test_disjoint_drag_to_middle(self):
        before = self.window._ordered_paths()
        self.window.list_widget._move_rows_to_target([0, 3], 2)
        self.assertEqual(self.window._ordered_paths(), [before[1], before[0], before[3], before[2]])

    def test_output_filename_cannot_escape_folder(self):
        self.window.dest_input.setText(self.temp.name)
        self.window.filename_input.setText("../escaped.pdf")
        self.window._merge_pdfs()
        self.assertIsNone(self.window._thread)

    def test_background_merge_finishes_and_can_run_again(self):
        self.window.dest_input.setText(self.temp.name)
        for name in ["merged1", "merged2"]:
            self.window.filename_input.setText(name)
            self.window._merge_pdfs()
            self.assertFalse(self.window.centralWidget().isEnabled())
            dialog = self.window._progress_dialog
            self.assertFalse(dialog.autoClose())
            self.window._merge_pdfs()  # A second invocation must not create another worker.
            deadline = time.monotonic() + 10
            while self.window._thread is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
            self.assertIsNone(self.window._thread)
            self.assertTrue(self.window.centralWidget().isEnabled())
            self.assertEqual(len(PdfReader(Path(self.temp.name) / (name + ".pdf")).pages), 10)

    def wait_for_worker(self):
        deadline = time.monotonic() + 10
        while self.window._thread is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertIsNone(self.window._thread)

    def test_rearrange_button_updates_counts_and_exports(self):
        self.select([0])
        self.assertTrue(self.window.pages_button.isEnabled())
        with patch("gui.main_window.PageSelectionDialog.getText", return_value=("3, 1", True)):
            self.window.pages_button.click()
        self.assertEqual(self.window.list_widget.item(0, 4).text(), "3, 1")
        self.assertEqual(self.window.list_widget.item(0, 5).text(), "2")
        self.assertEqual(self.window.total_pages_label.text(), "Total pages: 9")
        self.window.dest_input.setText(self.temp.name)
        self.window._merge_pdfs()
        self.wait_for_worker()
        self.assertEqual(len(PdfReader(Path(self.temp.name) / "Merge.pdf").pages), 9)

    def test_split_button_exports_groups(self):
        self.select([0])
        self.window.dest_input.setText(self.temp.name)
        with patch("gui.main_window.PageSelectionDialog.getText", return_value=("3-2; 1", True)):
            self.window.split_button.click()
        self.wait_for_worker()
        self.assertEqual(len(PdfReader(Path(self.temp.name) / "c_part_001.pdf").pages), 2)
        self.assertEqual(len(PdfReader(Path(self.temp.name) / "c_part_002.pdf").pages), 1)
        self.assertEqual(len(PdfReader(self.paths[0]).pages), 3)

    def test_page_dialog_cancel_preserves_selection(self):
        self.select([0])
        with patch("gui.main_window.PageSelectionDialog.getText", return_value=("2", False)):
            self.window.pages_button.click()
        self.assertEqual(self.window.list_widget.item(0, 4).text(), "All")
        self.select([0, 1])
        self.assertFalse(self.window.pages_button.isEnabled())
        self.assertFalse(self.window.split_button.isEnabled())

    def test_page_dialog_live_validation(self):
        dialog = PageSelectionDialog(self.window, "Page order", "Choose pages", "", 4)
        button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.assertTrue(button.isEnabled())
        dialog.edit.setText("5")
        self.assertFalse(button.isEnabled())
        self.assertIn("between 1 and 4", dialog.preview.text())
        dialog.edit.setText("4-2, 1")
        self.assertTrue(button.isEnabled())
        self.assertIn("4, 3, 2, 1", dialog.preview.text())
        dialog.close()

    def test_split_dialog_previews_output_count(self):
        dialog = PageSelectionDialog(self.window, "Split", "Choose groups", "1-2; 3-4", 4, True)
        self.assertIn("2 PDFs", dialog.preview.text())
        dialog.edit.clear()
        self.assertIn("4 PDFs", dialog.preview.text())
        dialog.close()

    def test_empty_list_disables_export(self):
        self.window._clear_list()
        self.assertFalse(self.window.merge_button.isEnabled())
        self.assertFalse(self.window.clear_button.isEnabled())
        self.assertIn("Add PDFs", self.window.selection_hint.text())

    def test_close_is_blocked_during_merge(self):
        self.window._thread = object()
        event = QCloseEvent()
        self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.window._thread = None


if __name__ == "__main__":
    unittest.main()
