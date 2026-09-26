# Arranca llama-server en Windows con los flags que soporte tu versión. Lee .env.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
Get-Content ".env" | Where-Object { $_ -match "^\s*[A-Z_]+=" } | ForEach-Object {
  $k, $v = $_ -split "=", 2; $v = ($v -split " #", 2)[0].Trim(); if ($v -and -not $v.StartsWith("#")) { Set-Item -Path "env:$k" -Value $v }
}
if (-not $env:GGUF_PATH -or -not (Test-Path $env:GGUF_PATH)) { throw "GGUF_PATH no definido o no existe: $env:GGUF_PATH" }
$np = if ($env:LLM_PARALLEL) { [int]$env:LLM_PARALLEL } else { 8 }
$ctx = if ($env:CTX_PER_SLOT) { [int]$env:CTX_PER_SLOT } else { 8192 }
$help = (& llama-server --help 2>&1 | Out-String)
function Has($flag) { return $help.Contains($flag) }
$args = @("--model", $env:GGUF_PATH, "--host", "0.0.0.0", "--port", ($(if ($env:LLM_PORT) { $env:LLM_PORT } else { "8080" })),
          "--ctx-size", ($np * $ctx), "--n-gpu-layers", ($(if ($env:GPU_LAYERS) { $env:GPU_LAYERS } else { "99" })))
if (Has "--parallel") { $args += @("--parallel", $np) }
if (Has "--cont-batching") { $args += "--cont-batching" }
if (Has "--threads") { $args += @("--threads", ($(if ($env:THREADS) { $env:THREADS } else { $env:NUMBER_OF_PROCESSORS }))) }
if (Has "--flash-attn") { if ($help -match "--flash-attn.*(on|auto)") { $args += @("--flash-attn", "on") } else { $args += "--flash-attn" } }
if (Has "--cache-type-k") { $args += @("--cache-type-k", "q8_0", "--cache-type-v", "q8_0") }
if (Has "--cache-reuse") { $args += @("--cache-reuse", "256") }
if (Has "--jinja") { $args += "--jinja" }
if ($env:DRAFT_GGUF -and (Test-Path $env:DRAFT_GGUF) -and (Has "--model-draft")) {
  $args += @("--model-draft", $env:DRAFT_GGUF)
  if (Has "--draft-max") { $args += @("--draft-max", ($(if ($env:DRAFT_MAX) { $env:DRAFT_MAX } else { "16" }))) }
  if (Has "--draft-min") { $args += @("--draft-min", ($(if ($env:DRAFT_MIN) { $env:DRAFT_MIN } else { "4" }))) }
}
Write-Host "llama-server $($args -join ' ')"
& llama-server @args
