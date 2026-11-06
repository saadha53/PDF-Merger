$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

python -m PyInstaller --noconfirm PDFMerger.spec

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

python scripts/smoke_test_build.py dist/PDFMerger.exe
if ($LASTEXITCODE -ne 0) {
  throw "The packaged application failed its startup check."
}
