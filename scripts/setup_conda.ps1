# Phase 1 helper: create or update the rag-company conda environment.
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup_conda.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Creating conda env from environment.yml ..."
conda env create -f environment.yml
if ($LASTEXITCODE -ne 0) {
    Write-Host "Env may already exist; updating ..."
    conda env update -f environment.yml --prune
}

Write-Host ""
Write-Host "Done. Activate with:"
Write-Host "  conda activate rag-company"
Write-Host "Then run:"
Write-Host "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
