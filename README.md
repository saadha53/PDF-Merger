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

Merging includes all pages. The page-range columns are reserved for a future
feature. Password-protected PDFs must be unlocked before adding them.
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
