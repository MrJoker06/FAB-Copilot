<#
.SYNOPSIS
    Start the locally deployed Qwen3.8-27B llama.cpp server used by Fab Insight Agent.

.DESCRIPTION
    Wraps the llama-server invocation recorded in records.txt into a repeatable launcher:
    it resolves model paths, picks a context/parallel profile that fits an A10 (23 GB),
    starts llama-server, and waits until /v1/models answers.

    Defaults match the hybrid-attention layout of qwen35 (65 blocks, full_attention_interval=4,
    4 KV heads, key/value length 256): only ~17 layers hold KV, so 81920 tokens with q8_0
    KV cache costs roughly 2.8 GB on top of the 15.66 GB Q4_K_M weights.

.EXAMPLE
    .\scripts\start-local-model.ps1
    .\scripts\start-local-model.ps1 -Model ridge -Profile 32k -Port 8081
    .\scripts\start-local-model.ps1 -Vision -Alias deepseek-v4-flash
#>
[CmdletBinding()]
param(
    [ValidateSet('q4km', 'ridge')]
    [string]$Model = 'q4km',

    [ValidateSet('32k', '80k')]
    [string]$Profile = '80k',

    # llama.cpp divides --ctx-size across parallel slots.  A single slot keeps the
    # whole window for one request, which long evidence bundles need; 2 slots halve
    # the per-request limit.  Defaults follow the profile.
    [ValidateSet(0, 1, 2)]
    [int]$Parallel = 0,

    [int]$Port = 8080,

    [string]$BindHost = '127.0.0.1',

    # Load the multimodal projector as well (only needed for image input).
    [switch]$Vision,

    # Override the model id advertised on /v1/models.
    [string]$Alias,

    # Disable MTP speculative decoding (requires qwen35.nextn_predict_layers > 0).
    [switch]$NoMtp,

    # Keep the Qwen thinking pass.  Disabled by default: with 27B on an A10 the
    # reasoning trace costs ~6-7k extra output tokens per answer (~3x latency).
    [switch]$Thinking,

    # Workspace that contains models/ and runtimes/. Defaults to this repo, or its parent
    # when the repo is a nested checkout inside the deployment workspace.
    [string]$DeploymentRoot,

    [int]$ReadyTimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$deployRoot = if ($DeploymentRoot) {
    (Resolve-Path -LiteralPath $DeploymentRoot).Path
} elseif (Test-Path -LiteralPath (Join-Path $repo 'models')) {
    $repo
} else {
    Split-Path -Parent $repo
}
$server = Join-Path $deployRoot 'runtimes\llama-cpp\llama-server.exe'
if (-not (Test-Path -LiteralPath $server)) {
    throw "llama-server not found: $server"
}

$models = @{
    q4km  = @{
        File         = 'Qwen3.8-27B-Q4_K_M-GGUF\Qwen3.8-27B-Q4_K_M.gguf'
        Mmproj       = 'Qwen3.8-27B-Q4_K_M-GGUF\mmproj-F16.gguf'
        DefaultAlias = 'Qwen3.8-27B-Q4_K_M'
    }
    ridge = @{
        File         = 'Qwen3.8-27B-Ridge-3.7bpw\Qwen3.8-27B-Ridge-3.7bpw.gguf'
        Mmproj       = 'Qwen3.8-27B-Ridge-3.7bpw\mmproj-Qwen3.8-27B-BF16.gguf'
        DefaultAlias = 'Qwen3.8-27B-Ridge-3.7bpw'
    }
}

$profiles = @{
    '32k' = @{ Ctx = 32768; Parallel = 1 }
    '80k' = @{ Ctx = 81920; Parallel = 1 }
}

$selected = $models[$Model]
$modelPath = Join-Path $deployRoot ('models\' + $selected.File)
$mmprojPath = Join-Path $deployRoot ('models\' + $selected.Mmproj)
if (-not (Test-Path -LiteralPath $modelPath)) {
    throw "model file not found: $modelPath"
}
if ($Vision -and -not (Test-Path -LiteralPath $mmprojPath)) {
    throw "mmproj not found: $mmprojPath"
}

$modelId = if ($Alias) { $Alias } else { $selected.DefaultAlias }
$profileSpec = @{} + $profiles[$Profile]
if ($Parallel -gt 0) { $profileSpec.Parallel = $Parallel }

$arguments = @(
    '--model', $modelPath,
    '--host', $BindHost,
    '--port', "$Port",
    '--alias', $modelId,
    '--gpu-layers', 'all',
    '--ctx-size', "$($profileSpec.Ctx)",
    '--parallel', "$($profileSpec.Parallel)",
    '--batch-size', '1024',
    '--ubatch-size', '256',
    '--cache-type-k', 'q8_0',
    '--cache-type-v', 'q8_0',
    '--flash-attn', 'on',
    '--jinja',
    '--no-context-shift',
    '--fit', 'off'
)
if ($Vision) { $arguments += @('--mmproj', $mmprojPath) }
if (-not $NoMtp) { $arguments += @('--spec-type', 'draft-mtp', '--spec-draft-n-max', '2') }
if (-not $Thinking) { $arguments += @('--reasoning', 'off') }

$logDir = Join-Path $repo 'runtime\local-model'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdout = Join-Path $logDir "server-$Model-$Profile-$Port-$stamp.out.log"
$stderr = Join-Path $logDir "server-$Model-$Profile-$Port-$stamp.err.log"

Write-Host "llama-server: $server"
Write-Host "model       : $modelPath"
Write-Host "context     : $($profileSpec.Ctx) per slot (parallel $($profileSpec.Parallel))"
Write-Host "endpoint    : http://${BindHost}:$Port/v1"
Write-Host "logs        : $stderr"

$process = Start-Process -FilePath $server -ArgumentList $arguments -PassThru -NoNewWindow `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr

$deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
$ready = $false
while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) {
        throw "llama-server exited with code $($process.ExitCode). See $stderr"
    }
    try {
        $modelsResponse = Invoke-RestMethod -Uri "http://${BindHost}:$Port/v1/models" -TimeoutSec 3
        if ($modelsResponse.data) { $ready = $true; break }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $ready) {
    throw "llama-server did not become ready within $ReadyTimeoutSeconds seconds. See $stderr"
}

$served = ($modelsResponse.data | Select-Object -First 1).id
Write-Host ""
Write-Host "ready: pid=$($process.Id)  model_id=$served"
Write-Host "point Fab Insight Agent at it:"
Write-Host "  FAB_MODEL_PROVIDER=openai-compatible"
Write-Host "  FAB_MODEL_BASE_URL=http://${BindHost}:$Port/v1"
Write-Host "  FAB_MODEL_NAME=$served"
Write-Host "  FAB_MODEL_API_KEY=local   # any non-empty value"



