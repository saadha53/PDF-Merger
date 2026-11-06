# PDF-Merger

Desktop PDF merger using PyQt6 and pypdf. Add or drop PDF files, sort by a
column or reorder with drag-and-drop / Move Up / Move Down, then choose a
destination and merge. Files are merged in the displayed order.

## Run from source

Use Python 3.10 or later:

1. `python -m venv .venv`
2. `.venv\Scripts\Activate.ps1`
3. `python -m pip install -r requirements.txt`
4. `python main.py`

Select one file and click **Rearrange Pages** to choose pages in output order,
for example `3, 1-2, 5-4`. Blank restores all pages; repeated pages are allowed.
The dialog previews page order and validates ranges as you type. You can also
double-click a document to open it. The table shows the selection and output page
count. Click **Save PDF** (one file) or **Merge PDFs** (multiple files)
to export one rearranged PDF or combine the selected pages from all listed files.

To split, select one file, choose a destination folder, and click **Split PDF**.
Enter groups separated by semicolons (`1-3; 4-6; 7`), or leave blank for one file
per page. Outputs are named `<source>_part_001.pdf`, `<source>_part_002.pdf`, etc.
Split groups refer to original page numbers, independent of the rearrange setting.
The overwrite checkbox applies to every split output. Existing-file conflicts and
invalid groups are checked before writing; if a later disk error interrupts a
split, the error reports how many files were saved.

Use **Add PDFs** or Ctrl+O to choose files. Selecting rows reveals which actions
are available; full source paths and modification dates appear in filename tooltips.

Password-protected PDFs must be unlocked before adding them.
Input PDFs cannot be replaced by the output. Existing output files are replaced
only when overwrite is enabled, after the new PDF has been written successfully.

## Tests

`python -B -m unittest discover -s tests -v`

The suite exercises PDF output safety and Qt table/worker behavior offscreen.

## Portable build (Windows)

1. `python -m pip install -r requirements.txt`
2. `python -m pip install -r requirements-dev.txt`
3. `powershell -ExecutionPolicy Bypass -File scripts/build_portable.ps1`

The single-file portable app will be `dist/PDFMerger.exe`.
Rebuild after source changes; existing binaries are not updated by running tests.
The build uses `PDFMerger.spec` to isolate DLL discovery from unrelated tools on
PATH and bundle the build machine's Microsoft Visual C++ x64 runtime. Install
that runtime on the build machine before packaging. The build script also runs
the resulting executable with `--smoke-test` to verify Qt startup offscreen.
