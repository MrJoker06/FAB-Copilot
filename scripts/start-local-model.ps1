<#
.SYNOPSIS
    Start the locally deployed Qwen3.8-27B llama.cpp server used by Fab Insight Agent.

.DESCRIPTION
    Thin Windows wrapper around scripts/start_local_model.py, which holds the single
    cross-platform implementation (path resolution, profiles, readiness check).  On
    Linux run `python3 scripts/start_local_model.py` directly with the same options.

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

    [int]$Port = 8080,

    [string]$BindHost = '127.0.0.1',

    [switch]$Vision,

    [string]$Alias,

    [switch]$NoMtp,

    [switch]$Thinking,

    [string]$DeploymentRoot,

    [string]$Server,

    [int]$ReadyTimeoutSeconds = 180,

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot 'start_local_model.py'

$python = $null
$prefix = @()
if ($env:FAB_PYTHON) {
    $python = $env:FAB_PYTHON
} elseif (Test-Path -LiteralPath (Join-Path $repo '.venv-win\Scripts\python.exe')) {
    $python = Join-Path $repo '.venv-win\Scripts\python.exe'
} elseif (Test-Path -LiteralPath (Join-Path $repo '.venv\Scripts\python.exe')) {
    $python = Join-Path $repo '.venv\Scripts\python.exe'
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = 'python'
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = 'py'
    $prefix = @('-3')
} else {
    throw 'Python 3 is required. Set FAB_PYTHON or create .venv-win.'
}

$arguments = @(
    '--model', $Model,
    '--profile', $Profile,
    '--port', "$Port",
    '--host', $BindHost,
    '--ready-timeout', "$ReadyTimeoutSeconds"
)
if ($Vision) { $arguments += '--vision' }
if ($Alias) { $arguments += @('--alias', $Alias) }
if ($NoMtp) { $arguments += '--no-mtp' }
if ($Thinking) { $arguments += '--thinking' }
if ($DeploymentRoot) { $arguments += @('--deployment-root', $DeploymentRoot) }
if ($Server) { $arguments += @('--server', $Server) }
if ($DryRun) { $arguments += '--dry-run' }

& $python @prefix $launcher @arguments
exit $LASTEXITCODE
