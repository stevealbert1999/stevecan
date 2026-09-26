# Detiene y elimina las tareas programadas de stevecan.
foreach ($n in "stevecan-llama", "stevecan-agents", "stevecan-api") {
  Stop-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
  Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "eliminada: $n"
}
