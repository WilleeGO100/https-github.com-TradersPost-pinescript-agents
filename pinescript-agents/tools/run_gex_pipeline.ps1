Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Import-EnvFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        $text = $line.Trim()
        if ([string]::IsNullOrWhiteSpace($text) -or $text.StartsWith("#")) {
            continue
        }
        if ($text.StartsWith("export ")) {
            $text = $text.Substring(7).Trim()
        }
        $eq = $text.IndexOf("=")
        if ($eq -lt 1) {
            continue
        }
        $key = $text.Substring(0, $eq).Trim()
        $value = $text.Substring($eq + 1).Trim()
        if (
            $value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))
        ) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if (-not [string]::IsNullOrWhiteSpace($key) -and -not (Test-Path "Env:$key")) {
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Import-EnvFile -Path (Join-Path $repoRoot ".env")
Import-EnvFile -Path (Join-Path $repoRoot ".env_gex")

if ([string]::IsNullOrWhiteSpace($env:GEXBOT_API_KEY)) {
    throw "Missing GEXBOT_API_KEY. Set it in your environment or .env/.env_gex."
}

$today = Get-Date
$startDate = if ($env:START_DATE) { $env:START_DATE } else { $today.AddDays(-7).ToString("yyyy-MM-dd") }
$endDate = if ($env:END_DATE) { $env:END_DATE } else { $today.ToString("yyyy-MM-dd") }
$tickers = if ($env:TICKERS) { $env:TICKERS } else { "NQ_NDX,ES_SPX" }
$aggregationPeriod = if ($env:AGGREGATION_PERIOD) { $env:AGGREGATION_PERIOD } else { "zero" }
$topN = if ($env:TOP_N) { $env:TOP_N } else { "20" }
$timeout = if ($env:TIMEOUT) { $env:TIMEOUT } else { "30" }
$sleepMs = if ($env:SLEEP_MS) { $env:SLEEP_MS } else { "250" }
$outDir = if ($env:OUT_DIR) { $env:OUT_DIR } else { "pinescript-agents/projects/analysis/gexbot_data/historical" }
$futureDays = if ($env:FUTURE_DAYS) { $env:FUTURE_DAYS } else { "30" }
$forceLargePull = if ($env:FORCE_LARGE_PULL) { $env:FORCE_LARGE_PULL } else { "" }
$gexBlockMaxDays = if ($env:GEX_BLOCK_MAX_DAYS) { $env:GEX_BLOCK_MAX_DAYS } else { "45" }
$multiAssetStrategyPath = if ($env:MULTI_ASSET_STRATEGY_PATH) {
    $env:MULTI_ASSET_STRATEGY_PATH
} else {
    "pinescript-agents/projects/gex-compatible-strategies/multi_asset/BTC_tradingview_scalp_strategy.pine"
}

[datetime]$startDt = [datetime]::ParseExact($startDate, "yyyy-MM-dd", $null)
[datetime]$endDt = [datetime]::ParseExact($endDate, "yyyy-MM-dd", $null)
if ($endDt -lt $startDt) {
    throw "END_DATE must be >= START_DATE."
}

$days = ($endDt - $startDt).Days + 1
$weekdayCount = 0
for ($d = $startDt; $d -le $endDt; $d = $d.AddDays(1)) {
    if ($d.DayOfWeek -ne [DayOfWeek]::Saturday -and $d.DayOfWeek -ne [DayOfWeek]::Sunday) {
        $weekdayCount++
    }
}
$tickerCount = ($tickers.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ }).Count
if ($tickerCount -lt 1) {
    $tickerCount = 1
}
# Each day creates 3 files per ticker (raw, top json, top csv), plus a few summary/include artifacts.
$estimatedFiles = $weekdayCount * $tickerCount * 3
if ($estimatedFiles -gt 300 -and $forceLargePull -ne "1") {
    throw (
        "Safety stop: this run is estimated to create about $estimatedFiles files " +
        "($weekdayCount trading days x $tickerCount tickers x 3 files/day)." +
        " Narrow START_DATE/END_DATE, or set FORCE_LARGE_PULL=1 to allow this large backfill."
    )
}

$pullScript = Join-Path $repoRoot "pinescript-agents/tools/gexbot_pull_historical.py"
$blockScript = Join-Path $repoRoot "pinescript-agents/tools/gexbot_nq_to_pine_block.py"
$multiAssetRefreshScript = Join-Path $repoRoot "pinescript-agents/tools/gexbot_refresh_multi_asset_strategy.py"

Write-Host "Running historical pull for tickers: $tickers"
& python $pullScript `
    --api-key $env:GEXBOT_API_KEY `
    --tickers $tickers `
    --aggregation-period $aggregationPeriod `
    --start-date $startDate `
    --end-date $endDate `
    --skip-weekends `
    --top-n $topN `
    --timeout $timeout `
    --sleep-ms $sleepMs `
    --out-dir $outDir
if ($LASTEXITCODE -ne 0) {
    throw "Historical pull failed with exit code $LASTEXITCODE"
}

$nqHistOut = Join-Path $repoRoot "pinescript-agents/projects/generated/nq-gex-history.inc.pine"
$nqFwdOut = Join-Path $repoRoot "pinescript-agents/projects/generated/nq-gex-forward.inc.pine"
$esHistOut = Join-Path $repoRoot "pinescript-agents/projects/generated/es-gex-history.inc.pine"
$esFwdOut = Join-Path $repoRoot "pinescript-agents/projects/generated/es-gex-forward.inc.pine"
$nqReadyOut = Join-Path $repoRoot "pinescript-agents/projects/generated/nq-gex-ready-block.pine"
$esReadyOut = Join-Path $repoRoot "pinescript-agents/projects/generated/es-gex-ready-block.pine"

Write-Host "Building NQ Pine include files..."
& python $blockScript `
    --dir $outDir `
    --require-symbol NQ_NDX `
    --history-out $nqHistOut `
    --forward-out $nqFwdOut `
    --future-days $futureDays `
    --skip-weekends-forward
if ($LASTEXITCODE -ne 0) {
    throw "NQ include build failed with exit code $LASTEXITCODE"
}

Write-Host "Building ES Pine include files..."
& python $blockScript `
    --dir $outDir `
    --require-symbol ES_SPX `
    --history-out $esHistOut `
    --forward-out $esFwdOut `
    --future-days $futureDays `
    --skip-weekends-forward
if ($LASTEXITCODE -ne 0) {
    throw "ES include build failed with exit code $LASTEXITCODE"
}

# Build single-file ready blocks for fast strategy insertion.
$nqReady = @(
    "// AUTO-GENERATED READY BLOCK (NQ_NDX)"
    (Get-Content -LiteralPath $nqHistOut -Raw)
    ""
    (Get-Content -LiteralPath $nqFwdOut -Raw)
    "// END READY BLOCK (NQ_NDX)"
) -join "`r`n"
Set-Content -LiteralPath $nqReadyOut -Value $nqReady -Encoding utf8

$esReady = @(
    "// AUTO-GENERATED READY BLOCK (ES_SPX)"
    (Get-Content -LiteralPath $esHistOut -Raw)
    ""
    (Get-Content -LiteralPath $esFwdOut -Raw)
    "// END READY BLOCK (ES_SPX)"
) -join "`r`n"
Set-Content -LiteralPath $esReadyOut -Value $esReady -Encoding utf8

$multiAssetStrategyAbs = Join-Path $repoRoot $multiAssetStrategyPath
if (Test-Path -LiteralPath $multiAssetStrategyAbs) {
    Write-Host "Refreshing multi-asset strategy GEX blocks..."
    & python $multiAssetRefreshScript `
        --strategy $multiAssetStrategyAbs `
        --hist-dir $outDir `
        --max-days $gexBlockMaxDays
    if ($LASTEXITCODE -ne 0) {
        throw "Multi-asset strategy GEX refresh failed with exit code $LASTEXITCODE"
    }
} else {
    Write-Host "Multi-asset strategy not found, skipping refresh: $multiAssetStrategyAbs"
}

Write-Host ""
Write-Host "Done."
Write-Host "NQ history file: $nqHistOut"
Write-Host "ES history file: $esHistOut"
Write-Host "NQ forward file: $nqFwdOut"
Write-Host "ES forward file: $esFwdOut"
Write-Host "NQ ready block : $nqReadyOut"
Write-Host "ES ready block : $esReadyOut"
Write-Host "Multi-asset strategy refreshed: $multiAssetStrategyAbs"
