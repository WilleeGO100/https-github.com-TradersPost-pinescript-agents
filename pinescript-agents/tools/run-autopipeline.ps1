param(
    [int]$MaxAdd = 10,
    [int]$MinScore = 4,
    [int]$MaxVideos = 3,
    [string]$WhisperModel = "medium",
    [switch]$UseWhisper = $true,
    [switch]$RetryFailed,
    [string]$CookiesFromBrowser = "",
    [string]$Cookies = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir "..\..")

$ScoutScript = Join-Path $ScriptDir "video-scout.py"
$PipelineScript = Join-Path $ScriptDir "autopipeline.py"

Write-Host "==> Step 1/2: scouting videos..."
python $ScoutScript --max-add $MaxAdd --min-score $MinScore
if ($LASTEXITCODE -ne 0) {
    throw "video-scout.py failed with exit code $LASTEXITCODE"
}

Write-Host "==> Step 2/2: running pipeline..."
$pipelineArgs = @($PipelineScript, "--max-videos", "$MaxVideos")

if ($UseWhisper) {
    $pipelineArgs += @("--whisper", "--model", $WhisperModel)
}
if ($RetryFailed) {
    $pipelineArgs += "--retry-failed"
}
if ($CookiesFromBrowser) {
    $pipelineArgs += @("--cookies-from-browser", $CookiesFromBrowser)
}
if ($Cookies) {
    $pipelineArgs += @("--cookies", $Cookies)
}
if ($DryRun) {
    $pipelineArgs += "--dry-run"
}

python @pipelineArgs
if ($LASTEXITCODE -ne 0) {
    throw "autopipeline.py failed with exit code $LASTEXITCODE"
}

Write-Host "==> Done. Check projects/analysis and projects/analysis/pipeline_state.json"
