param(
  [string]$Python = "py -3.11",
  [string]$VenvDir = "$env:LOCALAPPDATA\KylinStock\ocr-venv"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Requirements = Join-Path $Root "src-tauri\resources\requirements-ocr.txt"

function Invoke-Python([string[]]$Arguments) {
  if ($Python -eq "py -3.11") {
    & py -3.11 @Arguments
  } else {
    & $Python @Arguments
  }
  if ($LASTEXITCODE -ne 0) { throw "Python command failed" }
}

Invoke-Python @("-c", "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'; print(sys.version)")
Invoke-Python @("-m", "venv", $VenvDir)

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$RapidOcr = Join-Path $VenvDir "Scripts\rapidocr.exe"
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $VenvPython -m pip install -r $Requirements
if ($LASTEXITCODE -ne 0) { throw "OCR dependency installation failed" }
& $RapidOcr check
if ($LASTEXITCODE -ne 0) { throw "RapidOCR self-check failed" }

Write-Host "OCR runtime ready: $VenvDir"
Write-Host "KylinStock will auto-discover this standard OCR environment when launched normally."
