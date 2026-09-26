# Instalación en Windows (PowerShell 5.1+ o 7): venv, dependencias y tareas programadas que arrancan
# llama-server, los agentes y la API al iniciar el sistema y los reinician si caen (24/7 sin WSL ni Docker).
# Ejecutar como administrador:  powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Creado .env: edita GGUF_PATH, PROJECT_DIRS, API_TOKEN" }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "python no está en el PATH (instala Python 3.11+ y marca 'Add to PATH')" }
if (-not (Get-Command llama-server -ErrorAction SilentlyContinue)) { Write-Warning "llama-server no está en el PATH: descarga llama.cpp (release win-cuda o win-cpu) y añade su carpeta al PATH" }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Warning "git no está en el PATH: instala Git for Windows (necesario para skills, docs y developer)" }
python -m venv .venv
& ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
$py = Join-Path $Root ".venv\Scripts\python.exe"
$tasks = @(
  @{ Name = "stevecan-llama";  Cmd = "powershell.exe"; Args = "-NoProfile -ExecutionPolicy Bypass -File `"$Root\scripts\windows\llama-server.ps1`"" },
  @{ Name = "stevecan-agents"; Cmd = "powershell.exe"; Args = "-NoProfile -ExecutionPolicy Bypass -File `"$Root\scripts\windows\run-forever.ps1`" -Module stevecan" },
  @{ Name = "stevecan-api";    Cmd = "powershell.exe"; Args = "-NoProfile -ExecutionPolicy Bypass -File `"$Root\scripts\windows\run-forever.ps1`" -Module stevecan.serve" }
)
foreach ($t in $tasks) {
  $action = New-ScheduledTaskAction -Execute $t.Cmd -Argument $t.Args -WorkingDirectory $Root
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
  $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
  Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
  Start-ScheduledTask -TaskName $t.Name
  Write-Host "tarea registrada y arrancada: $($t.Name)"
}
& $py -m stevecan.skills sync
& $py -m stevecan.docs sync
Write-Host "Listo. Estado: Get-ScheduledTask stevecan-* | Get-ScheduledTaskInfo ; logs en data\agents.log ; panel en http://localhost:8765/"
