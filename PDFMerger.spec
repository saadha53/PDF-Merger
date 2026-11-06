# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

# Prevent unrelated tools on PATH (for example Poppler/libheif) from supplying
# incompatible copies of Windows/ICU DLLs during dependency discovery.
os.environ['PATH'] = os.pathsep.join([
    str(Path(os.environ['SystemRoot']) / 'System32'),
    os.environ['SystemRoot'],
    str(Path(sys.base_prefix)),
    str(Path(sys.executable).parent),
])

# Prefer the build machine's installed VC runtime over stale copies shipped
# inside wheels. Keep every bundled copy consistent, including Qt's bin folder.
runtime_dir = Path(os.environ['SystemRoot']) / 'System32'
runtime_names = (
    'msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll',
    'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll',
    'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll',
)
runtime_files = {name: runtime_dir / name for name in runtime_names}
for path in runtime_files.values():
    if not path.is_file():
        raise RuntimeError(f'Install the Microsoft Visual C++ x64 runtime before building: {path}')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[(str(path), '.') for path in runtime_files.values()],
    datas=[('gui/assets/app_icon.ico', 'gui/assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
a.binaries = [
    (destination, str(runtime_files[Path(destination).name.lower()]), kind)
    if Path(destination).name.lower() in runtime_files else (destination, source, kind)
    for destination, source, kind in a.binaries
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDFMerger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['gui\\assets\\app_icon.ico'],
)
