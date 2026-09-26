# Ejecuta un módulo de stevecan en bucle: si el proceso termina, lo relanza a los 5 s (equivalente a Restart=always).
param([Parameter(Mandatory = $true)][string]$Module)
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$py = Join-Path $Root ".venv\Scripts\python.exe"
while ($true) {
  & $py -m $Module
  Write-Host "$Module terminó con código $LASTEXITCODE; reinicio en 5 s"
  Start-Sleep -Seconds 5
}
